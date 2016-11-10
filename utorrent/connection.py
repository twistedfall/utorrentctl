"""
uTorrentConnection
"""

import email.generator
import errno
import http.client
import http.cookiejar
import json
import re
import socket
import ssl as ssl_module
import time
import urllib.parse
import urllib.request
import urllib.request
from base64 import b64encode

import utorrent
import utorrent.uTorrent


class Connection:
	_connection = None
	_request = None
	_cookies = http.cookiejar.CookieJar( )
	_token = ""

	_retry_max = 3

	_utorrent = None

	@property
	def request_obj( self ):
		return self._request

	def __init__(self, host, login, password, ssl=False, ssl_verify=True):
		if ssl:
			self._url = "https://{}/".format( host )
		else:
			self._url = "http://{}/".format( host )
		self._request = urllib.request.Request( self._url )
		if ssl:
			ssl_context = None if ssl_verify else ssl_module._create_unverified_context()
			self._connection = http.client.HTTPSConnection(host, context=ssl_context)
		else:
			self._connection = http.client.HTTPConnection( host )
		self._connection.timeout = 10
		self._request.add_header( "Authorization", "Basic " + b64encode( "{}:{}".format( login, password ).encode( "latin1" ) ).decode( "ascii" ) )
		self._fetch_token( )

	def _make_request( self, loc, headers, data = None, retry = True ):
		last_e = None
		utserver_retry = False
		retries = 0
		max_retries = self._retry_max if retry else 1
		try:
			while retries < max_retries or utserver_retry:
				try:
					self._request.data = data
					self._connection.request( self._request.get_method( ), self._request.selector + loc, self._request.data, headers )
					resp = self._connection.getresponse( )
					if resp.status == 400:
						last_e = utorrent.uTorrentError( resp.read( ).decode( "utf8" ).strip( ) )
						# if uTorrent server alpha is bound to the same port as WebUI then it will respond with "invalid request" to the first request in the connection
						# apparently this is no longer the case, TODO: remove this hack
						if ( not self._utorrent or type( self._utorrent ) == utorrent.uTorrent.LinuxServer ) and not utserver_retry:
							utserver_retry = True
							continue
						raise last_e
					elif resp.status == 404 or resp.status == 401:
						raise utorrent.uTorrentError( "Request {}: {}".format( loc, resp.reason ) )
					elif resp.status != 200 and resp.status != 206:
						raise utorrent.uTorrentError( "{}: {}".format( resp.reason, resp.status ) )
					self._cookies.extract_cookies( resp, self._request )
					if len( self._cookies ) > 0:
						self._request.add_header( "Cookie", "; ".join(
							["{}={}".format( utorrent._url_quote( c.name ), utorrent._url_quote( c.value ) ) for c in self._cookies] ) )
					return resp
				# retry when utorrent returns bad data
				except ( http.client.CannotSendRequest, http.client.BadStatusLine ) as e:
					last_e = e
					self._connection.close( )
				# name resolution failed
				except socket.gaierror as e:
					raise utorrent.uTorrentError( e.strerror )
				# socket errors
				except socket.error as e:
					# retry on timeout
					if str( e ) == "timed out": # some peculiar handling for timeout error
						last_e = utorrent.uTorrentError( "Timeout after {} tries".format( max_retries ) )
						self._connection.close( )
					# retry after pause on specific windows errors
					elif e.errno == 10053 or e.errno == 10054:
						# Windows specific socket errors:
						# 10053 - An established connection was aborted by the software in your host machine
						# 10054 - An existing connection was forcibly closed by the remote host
						last_e = e
						self._connection.close( )
						time.sleep( 2 )
					elif e.errno == errno.ECONNREFUSED or e.errno == errno.ECONNRESET or errno == errno.EHOSTUNREACH:
						raise utorrent.uTorrentError( e.strerror )
					else:
						raise e
				retries += 1
			if last_e:
				raise last_e
		except Exception as e:
			self._connection.close( )
			raise e
		return None

	def _get_data( self, loc, data = None, retry = True, range_start = None, range_len = None, save_buffer = None, progress_cb = None ):
		headers = { k: v for k, v in self._request.header_items( ) }
		if data:
			bnd = email.generator._make_boundary( data )
			headers["Content-Type"] = "multipart/form-data; boundary={}".format( bnd )
			data = data.replace( "{{BOUNDARY}}", bnd )
		if range_start is not None:
			if range_len is None or range_len == 0:
				range_end = ""
			else:
				range_end = range_start + range_len - 1
			headers["Range"] = "bytes={}-{}".format( range_start, range_end )
		resp = self._make_request( loc, headers, data, retry )
		if save_buffer:
			read = 0
			resp_len = resp.length
			content_range = resp.getheader( "Content-Range" )
			if content_range is not None:
				m = re.match( "^bytes (\\d+)-\\d+/(\\d+)$", content_range )
				if m is not None:
					resp_len = int( m.group( 2 ) )
			while True:
				buf = resp.read( 10240 )
				read += len( buf )
				if progress_cb:
					progress_cb( range_start, read, resp_len )
				if len( buf ) == 0:
					break
				save_buffer.write( buf )
			self._connection.close( )
			return None
		out = resp.read( ).decode( "utf8" )
		self._connection.close( )
		return out

	def _fetch_token( self ):
		data = self._get_data( "gui/token.html" )
		match = re.search( "<div .*?id='token'.*?>(.+?)</div>", data )
		if match is None:
			raise utorrent.uTorrentError( "Can't fetch security token" )
		self._token = match.group( 1 )

	def _action_val( self, val ):
		if isinstance( val, bool ):
			val = int( val )
		return str( val )

	def _action( self, action, params = None, params_str = None ):
		args = []
		if params:
			for k, v in params.items( ):
				if utorrent.is_list_type( v ):
					for i in v:
						args.append( "{}={}".format( utorrent._url_quote( str( k ) ), utorrent._url_quote( self._action_val( i ) ) ) )
				else:
					args.append( "{}={}".format( utorrent._url_quote( str( k ) ), utorrent._url_quote( self._action_val( v ) ) ) )
		if params_str:
			params_str = "&" + params_str
		else:
			params_str = ""
		if action == "list":
			args.insert( 0, "token=" + self._token )
			args.insert( 1, "list=1" )
			section = "gui/"
		elif action == "proxy":
			section = "proxy"
		else:
			args.insert( 0, "token=" + self._token )
			args.insert( 1, "action=" + utorrent._url_quote( str( action ) ) )
			section = "gui/"
		return section + "?" + "&".join( args ) + params_str

	def do_action( self, action, params = None, params_str = None, data = None, retry = True, range_start = None, range_len = None, save_buffer = None,
	               progress_cb = None ):
		# uTorrent can send incorrect overlapping array objects, this will fix them, converting them to list
		def obj_hook( obj ):
			out = { }
			for k, v in obj:
				if k in out:
					out[k].extend( v )
				else:
					out[k] = v
			return out

		res = self._get_data( self._action( action, params, params_str ), data = data, retry = retry, range_start = range_start, range_len = range_len,
		                      save_buffer = save_buffer, progress_cb = progress_cb )
		if res:
			return json.loads( res, object_pairs_hook = obj_hook )
		else:
			return ""

	def utorrent( self, api = None ):
		if api == "linux":
			return utorrent.uTorrent.LinuxServer( self )
		elif api == "desktop":
			return utorrent.uTorrent.Desktop( self )
		elif api == "falcon":
			return utorrent.uTorrent.Falcon( self )
		else: # auto-detect
			try:
				ver = utorrent.uTorrent.Version( self.do_action( "getversion", retry = False ) )
			except utorrent.uTorrentError as e:
				if e.args[0] == "invalid request": # windows desktop uTorrent client
					ver = utorrent.uTorrent.Version.detect_from_settings( self.do_action( "getsettings" ) )
				else:
					raise e
			if ver.product == "server":
				return utorrent.uTorrent.LinuxServer( self, ver )
			elif ver.product == "desktop" or ver.product == "PRODUCT_CODE":
				if ver.major == 3:
					return utorrent.uTorrent.Falcon( self, ver )
				else:
					return utorrent.uTorrent.Desktop( self, ver )
			else:
				raise utorrent.uTorrentError( "Unsupported WebUI API" )
