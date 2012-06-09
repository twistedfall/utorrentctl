#!/usr/bin/env python3

"""
	This program is free software: you can redistribute it and/or modify
	it under the terms of the GNU Lesser General Public License as published by
	the Free Software Foundation, either version 3 of the License, or
	(at your option) any later version.

	This program is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public License
	along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

"""
	utorrentctl - uTorrent cli remote control utility and library
"""

from hashlib import sha1
from collections import OrderedDict
import base64
import datetime
import email.generator
import errno
import http.client
import http.cookiejar
import json
import ntpath
import os.path
import posixpath
import re
import socket
import string
import time
import urllib.parse
import urllib.request

def url_quote( string ):
	return urllib.parse.quote( string, "" )

def bdecode( data, str_encoding = "utf8" ):
	if not hasattr( data, "__next__" ):
		data = iter( data )
	out = None
	t = chr( next( data ) )
	if t == "e": # end of list/dict
		return None
	elif t == "i": # integer
		out = ""
		c = chr( next( data ) )
		while c != "e":
			out += c
			c = chr( next( data ) )
		out = int( out )
	elif t == "l": # list
		out = []
		while True:
			e = bdecode( data )
			if e == None:
				break
			out.append( e )
	elif t == "d": # dictionary
		out = {}
		while True:
			k = bdecode( data )
			if k == None:
				break
			out[k] = bdecode( data )
	elif t.isdigit(): # string
		out = ""
		l = t
		c = chr( next( data ) )
		while c != ":":
			l += c
			c = chr( next( data ) )
		bout = bytearray()
		for i in range( int( l ) ):
			bout.append( next( data ) )
		try:
			out = bout.decode( str_encoding )
		except UnicodeDecodeError:
			out = bout
	return out

def bencode( obj, str_encoding = "utf8" ):
	out = bytearray()
	t = type( obj )
	if t == int:
		out.extend( "i{}e".format( obj ).encode( str_encoding ) )
	elif t == dict:
		out.extend( b"d" )
		for k in sorted( obj.keys() ):
			out.extend( bencode( k ) )
			out.extend( bencode( obj[k] ) )
		out.extend( b"e" )
	elif t in ( bytes, bytearray ):
		out.extend( str( len( obj ) ).encode( str_encoding ) )
		out.extend( b":" )
		out.extend( obj )
	elif is_list_type( obj ):
		out.extend( b"l" )
		for e in map( bencode, obj ):
			out.extend( e )
		out.extend( b"e" )
	else:
		obj = str( obj ).encode( str_encoding )
		out.extend( str( len( obj ) ).encode( str_encoding ) )
		out.extend( b":" )
		out.extend( obj )
	return bytes( out )


def _get_external_attrs( cls ):
	return [ i for i in dir( cls ) if not re.search( "^_|_h$", i ) and not hasattr( getattr( cls, i ), "__call__" ) ]


def is_list_type( obj ):
	return hasattr( obj, "__iter__" ) and not isinstance( obj, ( str, bytes ) );


class uTorrentError( Exception ):
	pass


class Version:

	product = ""
	major = 0
	middle = 0
	minor = 0
	build = 0
	engine = 0
	ui = 0
	date = None
	user_agent = ""
	peer_id = ""
	device_id = ""

	@staticmethod
	def detect_from_settings( settings ):
		out = Version( settings )
		falcon = False
		for setting in settings["settings"]:
			if setting[0] == "webui.uconnect_enable": # only Falcon has this setting
				falcon = True
				out.major = 3
				out.middle = 0
				out.minor = 0
				break
		if not falcon:
			out.major = 2
			out.middle = 2
			out.minor = 0
		out.user_agent = "BTWebClient/{}{}{}0({})".format( out.major, out.middle, out.minor, out.build )
		out.peer_id = "UT{}{}{}0".format( out.major, out.middle, out.minor )
		return out

	def __init__( self, res ):
		if "version" in res: # server returns full data
			self.product = res["version"]["product_code"]
			self.major = res["version"]["major_version"]
			self.middle = 0
			self.minor = res["version"]["minor_version"]
			self.build = res["build"]
			self.engine = res["version"]["engine_version"]
			self.ui = res["version"]["ui_version"]
			date = res["version"]["version_date"].split( " " )
			self.date = datetime.datetime( *map( int, date[0].split( "-" ) + date[1].split( ":" ) ) )
			self.user_agent = res["version"]["user_agent"]
			self.peer_id = res["version"]["peer_id"]
			self.device_id = res["version"]["device_id"]
		elif "build" in res:
			# fill some partially made up values as desktop client doesn't provide full info, only build
			self.product = "desktop"
			self.build = self.engine = self.ui = res["build"]
		else:
			raise uTorrentError( "Cannot detect version from the supplied server response" )

	def __str__( self ):
		return self.user_agent

	def verbose_str( self ):
		return "{} {}/{} {} v{}.{}.{}.{}, engine v{}, ui v{}".format(
			self.user_agent, self.device_id, self.peer_id, self.product,
			self.major, self.middle, self.minor, self.build, self.engine, self.ui
		)


class TorrentStatus:

	_progress = 0

	_value = 0

	started = False
	checking = False
	start_after_check = False
	checked = False
	error = False
	paused = False
	queued = False # queued == False means forced
	loaded = False

	def __init__( self, status, percent_loaded = 0 ):
		self._value = status
		self._progress = percent_loaded
		self.started = bool( status & 1 )
		self.checking = bool( status & 2 )
		self.start_after_check = bool( status & 4 )
		self.checked = bool( status & 8 )
		self.error = bool( status & 16 )
		self.paused = bool( status & 32 )
		self.queued = bool( status & 64 )
		self.loaded = bool( status & 128 )

	# http://forum.utorrent.com/viewtopic.php?pid=381527#p381527
	def __str__( self ):
		if not self.loaded:
			return "Not loaded"
		if self.error:
			return "Error"
		if self.checking:
			return "Checked {:.1f}%".format( self._progress )
		if self.paused:
			if self.queued:
				return "Paused"
			else:
				return "[F] Paused"
		if self._progress == 100:
			if self.queued:
				if self.started:
					return "Seeding"
				else:
					return "Queued Seed"
			else:
				if self.started:
					return "[F] Seeding"
				else:
					return "Finished"
		else: # self._progress < 100
			if self.queued:
				if self.started:
					return "Downloading"
				else:
					return "Queued"
			else:
				if self.started:
					return "[F] Downloading"
#				else:
#					return "Stopped"
		return "Stopped"

	def __lt__( self, other ):
		return self._value < other._value


class Torrent:

	_utorrent = None

	hash = ""
	status = None
	name = ""
	size = 0
	size_h = ""
	progress = 0. # in percent
	downloaded = 0
	downloaded_h = ""
	uploaded = 0
	uploaded_h = ""
	ratio = 0.
	ul_speed = 0
	ul_speed_h = ""
	dl_speed = 0
	dl_speed_h = ""
	eta = 0
	eta_h = ""
	label = ""
	peers_connected = 0
	peers_total = 0
	seeds_connected = 0
	seeds_total = 0
	availability = 0
	availability_h = ""
	queue_order = 0
	dl_remain = 0
	dl_remain_h = ""

	_default_format = "{hash} {status} {progress}% {size} {dl_speed} {ul_speed} {ratio} {peer_info} eta: {eta} {name} {label}"
	_default_format_specs = {
		"status" : "{status: <15}",
		"name" : "{name: <60}",
		"size" : "{size_h: >9}",
		"progress" : "{progress: >5.1f}",
		"downloaded" : "{downloaded_h: >9}",
		"uploaded" : "{uploaded_h: >9}",
		"ratio" : "{ratio: <6.2f}",
		"dl_speed" : "{dl_speed_h: >12}",
		"ul_speed" : "{ul_speed_h: >12}",
		"eta" : "{eta_h: <7}",
		"label" : "{label}",
		"peers_connected" : "{peers_connected: <4}",
		"peers_total" : "{peers_total: <5}",
		"seeds_connected" : "{seeds_connected: <4}",
		"seeds_total" : "{seeds_total: <5}",
		"peer_info" : "{peer_info: <7}",
		"availability" : "{availability_h: >5.2}",
		"dl_remain" : "{dl_remain_h: >9}",
	}

	def __init__( self, utorrent, torrent = None ):
		self._utorrent = utorrent
		if torrent:
			self.fill( torrent )

	def __str__( self ):
		return "{} {}".format( self.hash, self.name )

	def _process_format( self, format_string ):
		out = []
		args = dict( self.__dict__ )
		args["peer_info"] = ( "{peers_connected}/{peers_total}" if args["progress"] == 100 else "{seeds_connected}/{seeds_total}" ).format( **args )
		args["label"] = "({label})".format( **args ) if args["label"] != "" else ""
		if args["dl_speed"] < 1024:
			args["dl_speed_h"] = ""
		if args["ul_speed"] < 1024:
			args["ul_speed_h"] = ""
		if args["dl_remain"] == 0:
			args["dl_remain_h"] = ""
		formatter = string.Formatter()
		for literal_text, field_name, format_spec, conversion in formatter.parse( format_string ):
			elem = { "before" : literal_text, "value" : "" }
			if field_name != None:
				def_field_name, def_format_spec, def_conversion = None, " <20", None
				if field_name in self._default_format_specs:
					def_field_name, def_format_spec, def_conversion = next( formatter.parse( self._default_format_specs[field_name] ) )[1:4]
				val = formatter.get_field( field_name if def_field_name == None else def_field_name, None, args )[0]
				val = formatter.convert_field( val, conversion if conversion != None else def_conversion )
				val = formatter.format_field( val, format_spec if format_spec != "" else def_format_spec )
				elem["value"] = val
			out.append( elem )
		return out

	def _format_to_str( self, format_res ):
		out = ""
		for i in format_res:
			out += i["before"] + i["value"]
		return out.strip()

	def verbose_str( self, format_string = None ):
		return self._format_to_str( self._process_format( self._default_format if format_string == None else format_string ) )

	def fill( self, torrent ):
		self.hash, status, self.name, self.size, progress, self.downloaded, \
			self.uploaded, ratio, self.ul_speed, self.dl_speed, self.eta, self.label, \
			self.peers_connected, self.peers_total, self.seeds_connected, self.seeds_total, \
			self.availability, self.queue_order, self.dl_remain = torrent
		self._utorrent.check_hash( self.hash )
		self.progress = progress / 10.
		self.ratio = ratio / 1000.
		self.status = TorrentStatus( status, self.progress )
		self.size_h = uTorrent.human_size( self.size )
		self.uploaded_h = uTorrent.human_size( self.uploaded )
		self.downloaded_h = uTorrent.human_size( self.downloaded )
		self.ul_speed_h = uTorrent.human_size( self.ul_speed ) + "/s"
		self.dl_speed_h = uTorrent.human_size( self.dl_speed ) + "/s"
		self.eta_h = uTorrent.human_time_delta( self.eta )
		self.availability_h = self.availability / 65535.
		self.dl_remain_h = uTorrent.human_size( self.dl_remain )

	@classmethod
	def get_readonly_attrs( cls ):
		return tuple( set( _get_external_attrs( cls ) ) - set( ( "label", ) ) )

	@classmethod
	def get_public_attrs( cls ):
		return tuple( set( _get_external_attrs( cls ) ) - set( cls.get_readonly_attrs() ) )

	def info( self ):
		return self._utorrent.torrent_info( self )

	def file_list( self ):
		return self._utorrent.file_list( self )

	def start( self, force = False ):
		return self._utorrent.torrent_start( self, force )

	def stop( self ):
		return self._utorrent.torrent_stop( self )

	def pause( self ):
		return self._utorrent.torrent_pause( self )

	def resume( self ):
		return self._utorrent.torrent_resume( self )

	def recheck( self ):
		return self._utorrent.torrent_recheck( self )

	def remove( self, with_data = False ):
		return self._utorrent.torrent_remove( self, with_data )


class Torrent_API2( Torrent ):

	url = ""
	rss_url = ""
	status_message = ""
	_unk_hash = ""
	added_on = 0
	completed_on = 0
	_unk_str = 0
	download_dir = ""

	def __init__( self, utorrent, torrent = None ):
		Torrent.__init__( self, utorrent, torrent )
		self._default_format_specs["status"] = "{status_message: <15}"
		self._default_format_specs["completed_on"] = "{completed_on!s}"
		self._default_format_specs["added_on"] = "{added_on!s}"

	def fill( self, torrent ):
		Torrent.fill( self, torrent[0:19] )
		self.url, self.rss_url, self.status_message, self._unk_hash, self.added_on, \
			self.completed_on, self._unk_str, self.download_dir = torrent[19:27]
		self.added_on = datetime.datetime.fromtimestamp( self.added_on )
		self.completed_on = datetime.datetime.fromtimestamp( int( self.completed_on ) )

	def remove( self, with_data = False, with_torrent = False ):
		return self._utorrent.torrent_remove( self, with_data, with_torrent )


class Label:

	name = ""
	torrent_count = 0

	def __init__( self, label ):
		self.name, self.torrent_count = label

	def __str__( self ):
		return "{} ({})".format( self.name, self.torrent_count )


class Priority:

	value = 0

	def __init__( self, priority ):
		priority = int( priority )
		if priority in range( 4 ):
			self.value = priority
		else:
			self.value = 2

	def __str__( self ):
		if self.value == 0:
			return "don't download"
		elif self.value == 1:
			return "low priority"
		elif self.value == 2:
			return "normal priority"
		elif self.value == 3:
			return "high priority"
		else:
			return "unknown priority"


class File:

	_utorrent = None

	_parent_hash = ""

	index = 0
	hash = ""
	name = ""
	size = 0
	size_h = ""
	downloaded = 0
	downloaded_h = ""
	priority = None
	progress = 0.

	def __init__( self, utorrent, parent_hash, index, file = None ):
		self._utorrent = utorrent
		self._utorrent.check_hash( parent_hash )
		self._parent_hash = parent_hash
		self.index = index
		self.hash = "{}.{}".format( self._parent_hash, self.index )
		if file:
			self.fill( file )

	def __str__( self ):
		return "{} {}".format( self.hash, self.name )

	def verbose_str( self ):
		return "{: <44} [{: <15}] {: >5}% ({: >9} / {: >9}) {}".format( self.hash, self.priority, self.progress, \
			self.downloaded_h, self.size_h, self.name )

	def fill( self, file ):
		self.name, self.size, self.downloaded, priority = file[:4]
		self.priority = Priority( priority )
		if self.size == 0:
			self.progress = 100
		else:
			self.progress = round( float( self.downloaded ) / self.size * 100, 1 )
		self.size_h = uTorrent.human_size( self.size )
		self.downloaded_h = uTorrent.human_size( self.downloaded )

	def set_priority( self, priority ):
		self._utorrent.file_set_priority( { self.hash : priority } )


class File_API2( File ):

	def fill( self, file ):
		File.fill( self, file[:4] )


class JobInfo:

	_utorrent = None

	hash = ""
	trackers = []
	ulrate = 0
	ulrate_h = ""
	dlrate = 0
	dlrate_h = ""
	superseed = 0
	dht = 0
	pex = 0
	seed_override = 0
	seed_ratio = 0
	seed_time = 0

	def __init__( self, utorrent, hash = None, jobinfo = None ):
		self._utorrent = utorrent
		self.hash = hash
		if jobinfo:
			self.fill( jobinfo )

	def __str__( self ):
		return "Limits D:{} U:{}".format( self.dlrate, self.ulrate )

	def verbose_str( self ):
		return str( self ) + "  Superseed:{}  DHT:{}  PEX:{}  Queuing override:{}  Seed ratio:{}  Seed time:{}".format(
			self._tribool_status_str( self.superseed ), self._tribool_status_str( self.dht ),
			self._tribool_status_str( self.pex ), self._tribool_status_str( self.seed_override ), self.seed_ratio,
			uTorrent.human_time_delta( self.seed_time )
		)

	def fill( self, jobinfo ):
		self.hash = jobinfo["hash"]
		self.trackers = jobinfo["trackers"].strip().split( "\r\n\r\n" )
		self.ulrate = jobinfo["ulrate"]
		self.ulrate_h = uTorrent.human_size( self.ulrate ) + "/s"
		self.dlrate = jobinfo["dlrate"]
		self.dlrate_h = uTorrent.human_size( self.dlrate ) + "/s"
		self.superseed = jobinfo["superseed"]
		self.dht = jobinfo["dht"]
		self.pex = jobinfo["pex"]
		self.seed_override = jobinfo["seed_override"]
		self.seed_ratio = jobinfo["seed_ratio"]
		self.seed_time = jobinfo["seed_time"]

	@classmethod
	def get_public_attrs( cls ):
		return _get_external_attrs( cls )

	def _tribool_status_str( self, status ):
		return "not allowed" if status == -1 else ( "disabled" if status == 0 else "enabled" )


class RssFeedEntry:

	name = ""
	name_full = ""
	url = ""
	quality = 0
	codec = 0
	timestamp = 0
	season = 0
	episode = 0
	episode_to = 0
	feed_id = 0
	repack = False
	in_history = False

	def __init__( self, entry ):
		self.fill( entry )

	def __str__( self ):
		return "{}".format( self.name )

	def verbose_str( self ):
		return "{} {}".format( '*' if self.in_history else ' ', self.name_full )

	def fill( self, entry ):
		self.name, self.name_full, self.url, self.quality, self.codec, self.timestamp, self.season, self.episode, \
			self.episode_to, self.feed_id, self.repack, self.in_history = entry
		try:
			self.timestamp = datetime.datetime.fromtimestamp( self.timestamp )
		except ValueError: # utorrent 2.2 sometimes gives too large timestamp
			pass


class RssFeed:

	id = 0
	enabled = False
	use_feed_title = False
	user_selected = False
	programmed = False
	download_state = 0
	url = ""
	next_update = 0
	entries = None

	def __init__( self, feed ):
		self.fill( feed )

	def __str__( self ):
		return "{: <3} {: <3} {}".format( self.id, "on" if self.enabled else "off", self.url )

	def verbose_str( self ):
		return "{} ({}/{}) update: {}".format(
			str( self ), len( [ x for x in self.entries if x.in_history ] ), len( self.entries ), self.next_update
		)

	def fill( self, feed ):
		self.id, self.enabled, self.use_feed_title, self.user_selected, self.programmed, \
			self.download_state, self.url, self.next_update = feed[0:8]
		self.next_update = datetime.datetime.fromtimestamp( self.next_update )
		self.entries = []
		for e in feed[8]:
			self.entries.append( RssFeedEntry( e ) )

	@classmethod
	def get_readonly_attrs( cls ):
		return ( "id", "use_feed_title", "user_selected", "programmed", "download_state", "next_update", "entries" )

	@classmethod
	def get_writeonly_attrs( cls ):
		return ( "download_dir", "alias", "subscribe", "smart_filter" )

	@classmethod
	def get_public_attrs( cls ):
		return tuple( set( _get_external_attrs( cls ) ) - set( cls.get_readonly_attrs() ) )


class RssFilter:

	id = 0
	flags = 0
	name = ""
	filter = None
	not_filter = None
	save_in = ""
	feed_id = 0
	quality = 0
	label = ""
	postpone_mode = False
	last_match = 0
	smart_ep_filter = 0
	repack_ep_filter = 0
	episode = ""
	episode_filter = False
	resolving_candidate = False

	def __init__( self, filter_props ):
		self.fill( filter_props )

	def __str__( self ):
		return "{: <3} {: <3} {}".format( self.id, "on" if self.enabled else "off", self.name )

	def verbose_str( self ):
		return "{} {} -> {}: +{}-{}".format( str( self ), self.filter, self.save_in, self.filter, \
			self.not_filter )

	def fill( self, filter_props ):
		self.id, self.flags, self.name, self.filter, self.not_filter, self.save_in, self.feed_id, \
			self.quality, self.label, self.postpone_mode, self.last_match, self.smart_ep_filter, \
			self.repack_ep_filter, self.episode, self.episode_filter, self.resolving_candidate = filter_props
		self.postpone_mode = bool( self.postpone_mode )

	@classmethod
	def get_readonly_attrs( cls ):
		return ( "id", "flags", "last_match", "resolving_candidate", "enabled" )

	@classmethod
	def get_writeonly_attrs( cls ):
		return ( "prio", "add_stopped" )

	@classmethod
	def get_public_attrs( cls ):
		return tuple( set( _get_external_attrs( cls ) ) - set( cls.get_readonly_attrs() ) )

	@property
	def enabled( self ):
		return bool( self.flags & 1 )


class uTorrentConnection( http.client.HTTPConnection ):

	_host = ""
	_login = ""
	_password = ""

	_request = None
	_cookies = http.cookiejar.CookieJar()
	_token = ""

	_retry_max = 3

	_utorrent = None

	@property
	def request_obj( self ):
		return self._request

	def __init__( self, host, login, password ):
		self._host = host
		self._login = login
		self._password = password
		self._url = "http://{}/".format( self._host )
		self._request = urllib.request.Request( self._url )
		self._request.add_header( "Authorization", "Basic " + base64.b64encode( "{}:{}".format( self._login, self._password ).encode( "latin1" ) ).decode( "ascii" ) )
		http.client.HTTPConnection.__init__( self, self._request.host, timeout = 10 )
		self._fetch_token()

	def _make_request( self, loc, headers, data = None, retry = True ):
		last_e = None
		utserver_retry = False
		retries = 0
		max_retries = self._retry_max if retry else 1
		try:
			while retries < max_retries or utserver_retry:
				try:
					self._request.add_data( data )
					self.request( self._request.get_method(), self._request.get_selector() + loc, self._request.get_data(), headers )
					resp = self.getresponse()
					if resp.status == 400:
						last_e = uTorrentError( resp.read().decode( "utf8" ).strip() )
						# if uTorrent server alpha is bound to the same port as WebUI then it will respond with "invalid request" to the first request in the connection
						# apparently this is no longer the case, TODO: remove this hack
						if ( not self._utorrent or type( self._utorrent ) == uTorrentLinuxServer ) and not utserver_retry:
							utserver_retry = True
							continue
						raise last_e
					elif resp.status == 404 or resp.status == 401:
						raise uTorrentError( "Request {}: {}".format( loc, resp.reason ) )
					elif resp.status != 200:
						raise uTorrentError( "{}: {}".format( resp.reason, resp.status ) )
					self._cookies.extract_cookies( resp, self._request )
					if len( self._cookies ) > 0:
						self._request.add_header( "Cookie", "; ".join( [ "{}={}".format( url_quote( c.name ), url_quote( c.value ) ) for c in self._cookies ] ) )
					return resp
				# retry when utorrent returns bad data
				except ( http.client.CannotSendRequest, http.client.BadStatusLine ) as e:
					last_e = e
					self.close()
				# socket errors
				except socket.error as e:
					# retry on timeout
					if str( e ) == "timed out": # some peculiar handling for timeout error
						last_e = uTorrentError( "Timeout after {} tries".format( max_retries ) )
						self.close()
					# retry after pause on specific windows errors
					elif e.errno == 10053 or e.errno == 10054:
						# Windows specific socket errors:
						# 10053 - An established connection was aborted by the software in your host machine
						# 10054 - An existing connection was forcibly closed by the remote host
						last_e = e
						self.close()
						time.sleep( 2 )
					elif e.errno == errno.ECONNREFUSED or e.errno == errno.ECONNRESET or errno == errno.EHOSTUNREACH:
						raise uTorrentError( e.strerror )
					else:
						raise e
				# name resolution failed
				except socket.gaierror as e:
					raise uTorrentError( e.strerror )
				retries += 1
			if last_e:
				raise last_e
		except Exception as e:
			self.close()
			raise e
		return None

	def _get_data( self, loc, data = None, retry = True, save_buffer = None, progress_cb = None ):
		headers = { k : v for k, v in self._request.header_items() }
		if data:
			bnd = email.generator._make_boundary( data )
			headers["Content-Type"] = "multipart/form-data; boundary={}".format( bnd )
			data = data.replace( "{{BOUNDARY}}", bnd )
		resp = self._make_request( loc, headers, data, retry )
		if save_buffer:
			read = 0
			resp_len = resp.length
			while True:
				buf = resp.read( 10240 )
				read += len( buf )
				if progress_cb:
					progress_cb( read, resp_len )
				if len( buf ) == 0:
					break
				save_buffer.write( buf )
			self.close()
			return None
		out = resp.read().decode( "utf8" )
		self.close()
		return out

	def _fetch_token( self ):
		data = self._get_data( "gui/token.html" )
		match = re.search( "<div .*?id='token'.*?>(.+?)</div>", data )
		if match == None:
			raise uTorrentError( "Can't fetch security token" )
		self._token = match.group( 1 )

	def _action_val( self, val ):
		if isinstance( val, bool ):
			val = int( val )
		return str( val )

	def _action( self, action, params = None, params_str = None ):
		args = []
		if params:
			for k, v in params.items():
				if is_list_type( v ):
					for i in v:
						args.append( "{}={}".format( url_quote( str( k ) ), url_quote( self._action_val( i ) ) ) )
				else:
					args.append( "{}={}".format( url_quote( str( k ) ), url_quote( self._action_val( v ) ) ) )
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
			args.insert( 1, "action=" + url_quote( str( action ) ) )
			section = "gui/"
		return section + "?" + "&".join( args ) + params_str

	def do_action( self, action, params = None, params_str = None, data = None, retry = True, save_buffer = None, progress_cb = None ):
		# uTorrent can send incorrect overlapping array objects, this will fix them, converting them to list
		def obj_hook( obj ):
			out = {}
			for k, v in obj:
				if k in out:
					out[k].extend( v )
				else:
					out[k] = v
			return out
		res = self._get_data( self._action( action, params, params_str ), data = data, retry = retry, save_buffer = save_buffer, progress_cb = progress_cb )
		if res:
			return json.loads( res, object_pairs_hook = obj_hook )
		else:
			return ""

	def utorrent( self, api = None ):
		if api == "linux":
			return uTorrentLinuxServer( self )
		elif api == "desktop":
			return uTorrent( self )
		elif api == "falcon":
			return uTorrentFalcon( self )
		else: # auto-detect
			try:
				ver = Version( self.do_action( "getversion", retry = False ) )
			except uTorrentError as e:
				if e.args[0] == "invalid request": # windows desktop uTorrent client
					ver = Version.detect_from_settings( self.do_action( "getsettings" ) )
				else:
					raise e
			if ver.product == "server":
				return uTorrentLinuxServer( self, ver )
			elif ver.product == "desktop":
				if ver.major == 3:
					return uTorrentFalcon( self, ver )
				else:
					return uTorrent( self, ver )
			else:
				raise uTorrentError( "Unsupported WebUI API" )


class uTorrent:

	_url = ""

	_connection = None
	_version = None

	_TorrentClass = Torrent
	_JobInfoClass = JobInfo
	_FileClass = File

	_pathmodule = ntpath

	_list_cache_id = 0
	_torrent_cache = None
	_rssfeed_cache = None
	_rssfilter_cache = None

	api_version = 1 # http://user.utorrent.com/community/developers/webapi

	@property
	def TorrentClass( self ):
		return self._TorrentClass

	@property
	def JobInfoClass( self ):
		return self._JobInfoClass

	@property
	def pathmodule( self ):
		return self._pathmodule

	def __init__( self, connection, version = None ):
		self._connection = connection
		self._connection._utorrent = self
		self._version = version

	@staticmethod
	def _setting_val( value_type, value ):
		# Falcon incorrectly sends type 0 and empty string for some fields (e.g. boss_pw and boss_key_salt)
		if value_type == 0 and value != '': # int
			return int( value )
		elif value_type == 1 and value != '': # bool
			return value == "true"
		else:
			return value

	@staticmethod
	def human_size( size, suffixes = ( "B", "kiB", "MiB", "GiB", "TiB" ) ):
		for s in suffixes:
			if size < 1024:
				if s == suffixes[0]:
					return "{}{}".format( round( size, 0 ), s )
				else:
					return "{:.2f}{}".format( round( size, 2 ), s )
			if s != suffixes[-1]:
				size /= 1024.
		return "{:.2f}{}".format( round( size, 2 ), suffixes[-1] )

	@staticmethod
	def human_time_delta( seconds, max_elems = 2 ):
		if seconds == -1:
			return "inf"
		out = []
		reducer = ( ( 60 * 60 * 24 * 7, "w" ), ( 60 * 60 * 24, "d" ), ( 60 * 60, "h" ), ( 60, "m" ), ( 1, "s" ) )
		for d, c in reducer:
			v = int( seconds / d )
			seconds -= d * v
			if v or len( out ) > 0:
				out.append( "{}{}".format( v, c ) )
			if len( out ) == max_elems:
				break
		if len( out ) == 0:
			out.append( "0{}".format( reducer[-1][1] ) )
		return " ".join( out )

	@staticmethod
	def is_hash( torrent_hash ):
		return re.match( "[0-9A-F]{40}$", torrent_hash, re.IGNORECASE )

	@staticmethod
	def get_info_hash( torrent_data ):
		return sha1( bencode( bdecode( torrent_data )["info"] ) ).hexdigest().upper()

	@classmethod
	def check_hash( cls, torrent_hash ):
		if not cls.is_hash( torrent_hash ):
			raise uTorrentError( "Incorrect hash: {}".format( torrent_hash ) )

	@classmethod
	def parse_hash_prop( cls, hash_prop ):
		if isinstance( hash_prop, ( File, Torrent, JobInfo ) ):
			hash_prop = hash_prop.hash
		try:
			parent_hash, prop = hash_prop.split( ".", 1 )
		except ValueError:
			parent_hash, prop = hash_prop, None
		parent_hash = parent_hash.upper()
		cls.check_hash( parent_hash )
		return parent_hash, prop

	def resolve_torrent_hashes( self, hashes, torrent_list = None ):
		out = []
		if torrent_list == None:
			torrent_list = self.torrent_list()
		for h in hashes:
			if h in torrent_list:
				out.append( torrent_list[h].name )
		return out

	def resolve_feed_ids( self, ids, rss_list = None ):
		out = []
		if rss_list == None:
			rss_list = utorrent.rss_list()
		for feed_id in ids:
			if int( feed_id ) in rss_list:
				out.append( rss_list[int( feed_id )].url )
		return out

	def resolve_filter_ids( self, ids, filter_list = None ):
		out = []
		if filter_list == None:
			filter_list = utorrent.rssfilter_list()
		for filter_id in ids:
			if int( filter_id ) in filter_list:
				out.append( filter_list[int( filter_id )].name )
		return out

	def parse_file_list_structure( self, file_list ):
		out = OrderedDict()
		for file in file_list:
			parts = file.name.split( self.pathmodule.sep )
			cur_out = out
			for i, part in enumerate( parts ):
				is_last = i == len( parts ) - 1
				if not part in cur_out:
					if not is_last:
						cur_out[part] = OrderedDict()
				if is_last:
					cur_out[part] = file
				else:
					cur_out = cur_out[part]
		return out

	def _create_torrent_upload( self, torrent_data, torrent_filename ):
		out = "\r\n".join( (
			"--{{BOUNDARY}}",
			'Content-Disposition: form-data; name="torrent_file"; filename="{}"'.format( url_quote( torrent_filename ) ),
			"Content-Type: application/x-bittorrent",
			"",
			torrent_data.decode( "latin1" ),
			"--{{BOUNDARY}}",
			"",
		) )
		return out

	def _get_hashes( self, torrents ):
		if not is_list_type( torrents ):
			torrents = ( torrents, )
		out = []
		for t in torrents:
			if isinstance( t, self._TorrentClass ):
				hsh = t.hash
			elif isinstance( t, str ):
				hsh = t
			else:
				raise uTorrentError( "Hash designation only supported via Torrent class or string" )
			self.check_hash( hsh )
			out.append( hsh )
		return out

	def _handle_download_dir( self, download_dir ):
		out = None
		if download_dir:
			out = self.settings_get()["dir_active_download"]
			if not self._pathmodule.isabs( download_dir ):
				download_dir = out + self._pathmodule.sep + download_dir
			self.settings_set( { "dir_active_download" : download_dir } )
		return out

	def _handle_prev_dir( self, prev_dir ):
		if prev_dir:
			self.settings_set( { "dir_active_download" : prev_dir } )

	def do_action( self, action, params = None, params_str = None, data = None, retry = True, save_buffer = None, progress_cb = None ):
		return self._connection.do_action( action = action, params = params, params_str = params_str, data = data, retry = retry, save_buffer = save_buffer, progress_cb = progress_cb )

	def version( self ):
		if not self._version:
			self._version = Version( self.do_action( "start" ) )
		return self._version

	def _fetch_torrent_list( self ):
		if self._list_cache_id:
			out = self.do_action( "list", { "cid" : self._list_cache_id } )
			# torrents
			for t in out["torrentm"]:
				del self._torrent_cache[t]
			for t in out["torrentp"]:
				self._torrent_cache[t[0]] = t
			# feeds
			for r in out["rssfeedm"]:
				del self._rssfeed_cache[r]
			for r in out["rssfeedp"]:
				self._rssfeed_cache[r[0]] = r
			# filters
			for f in out["rssfilterm"]:
				del self._rssfilter_cache[f]
			for f in out["rssfilterp"]:
				self._rssfilter_cache[f[0]] = f
		else:
			out = self.do_action( "list" )
			if "torrents" in out:
				self._torrent_cache = { hsh : torrent for hsh, torrent in [ ( t[0], t ) for t in out["torrents"] ] }
			if "rssfeeds" in out:
				self._rssfeed_cache = { feed_id : feed for feed_id, feed in [ ( r[0], r ) for r in out["rssfeeds"] ] }
			if "rssfilters" in out:
				self._rssfilter_cache = { filter_id : filter_props for filter_id, filter_props in [ ( f[0], f ) for f in out["rssfilters"] ] }
		self._list_cache_id = out["torrentc"]
		return out

	def torrent_list( self, labels = None, rss_feeds = None, rss_filters = None ):
		res = self._fetch_torrent_list()
		out = { h : self._TorrentClass( self, t ) for h, t in self._torrent_cache.items() }
		if labels != None:
			labels.extend( [ Label( i ) for i in res["label"] ] )
		if rss_feeds != None:
			for feed_id, feed in self._rssfeed_cache.items():
				rss_feeds[feed_id] = RssFeed( feed )
		if rss_filters != None:
			for filter_id, filter_props in self._rssfilter_cache.items():
				rss_filters[filter_id] = RssFilter( filter_props )
		return out

	def torrent_info( self, torrents ):
		res = self.do_action( "getprops", { "hash" : self._get_hashes( torrents ) } )
		if not "props" in res:
			return {}
		return { hsh : info for hsh, info in [ ( i["hash"], self._JobInfoClass( self, jobinfo = i ) ) for i in res["props"] ] }

	def torrent_add_url( self, url, download_dir = None ):
		prev_dir = self._handle_download_dir( download_dir )
		res = self.do_action( "add-url", { "s" : url } );
		self._handle_prev_dir( prev_dir )
		if "error" in res:
			raise uTorrentError( res["error"] )
		if url[0:7] == "magnet:":
			m = re.search( "urn:btih:([0-9A-F]{40})", url, re.IGNORECASE )
			if m:
				return m.group( 1 ).upper()
		return None

	def torrent_add_data( self, torrent_data, download_dir = None, filename = "default.torrent" ):
		prev_dir = self._handle_download_dir( download_dir )
		res = self.do_action( "add-file", data = self._create_torrent_upload( torrent_data, filename ) );
		self._handle_prev_dir( prev_dir )
		if "error" in res:
			raise uTorrentError( res["error"] )
		return self.get_info_hash( torrent_data )

	def torrent_add_file( self, filename, download_dir = None ):
		f = open( filename, "rb" )
		torrent_data = f.read()
		f.close()
		return self.torrent_add_data( torrent_data, download_dir, os.path.basename( filename ) )

	"""
	[
		{ "hash" : [
				{ "prop_name" : "prop_value" },
				...
			]
		},
		...
	]
	"""
	def torrent_set_props( self, props ):
		args = []
		for arg in props:
			for hsh, t_prop in arg.items():
				for name, value in t_prop.items():
					args.append( "hash={}&s={}&v={}".format( url_quote( hsh ), url_quote( name ), url_quote( str( value ) ) ) )
		self.do_action( "setprops", params_str = "&".join( args ) )

	def torrent_start( self, torrents, force = False ):
		if force:
			self.do_action( "forcestart", { "hash" : self._get_hashes( torrents ) } )
		else:
			self.do_action( "start", { "hash" : self._get_hashes( torrents ) } )

	def torrent_forcestart( self, torrents ):
		return self.torrent_start( torrents, True )

	def torrent_stop( self, torrents ):
		self.do_action( "stop", { "hash" : self._get_hashes( torrents ) } )

	def torrent_pause( self, torrents ):
		self.do_action( "pause", { "hash" : self._get_hashes( torrents ) } )

	def torrent_resume( self, torrents ):
		self.do_action( "unpause", { "hash" : self._get_hashes( torrents ) } )

	def torrent_recheck( self, torrents ):
		self.do_action( "recheck", { "hash" : self._get_hashes( torrents ) } )

	def torrent_remove( self, torrents, with_data = False ):
		if with_data:
			self.do_action( "removedata", { "hash" : self._get_hashes( torrents ) } )
		else:
			self.do_action( "remove", { "hash" : self._get_hashes( torrents ) } )

	def torrent_remove_with_data( self, torrents ):
		return self.torrent_remove( torrents, True )

	def torrent_get_magnet( self, torrents, self_tracker = False ):
		out = {}
		tors = self.torrent_list()
		for t in torrents:
			t = t.upper()
			utorrent.check_hash( t )
			if t in tors:
				if self_tracker:
					trackers = [ self._connection.request_obj.get_full_url() + "announce"]
				else:
					trackers = self.torrent_info( t )[t].trackers
				trackers = "&".join( [ "" ] + [ "tr=" + url_quote( t ) for t in trackers ] )
				out[t] = "magnet:?xt=urn:btih:{}&dn={}{}".format( url_quote( t.lower() ), url_quote( tors[t].name ), trackers )
		return out

	def file_list( self, torrents ):
		res = self.do_action( "getfiles", { "hash" : self._get_hashes( torrents ) } )
		out = {}
		if "files" in res:
			fi = iter( res["files"] );
			for hsh in fi:
				out[hsh] = [ self._FileClass( self, hsh, i, f ) for i, f in enumerate( next( fi ) ) ]
		return out

	def file_set_priority( self, files ):
		args = []
		filecount_cache = {}
		for hsh, prio in files.items():
			parent_hash, index = self.parse_hash_prop( hsh )
			if not isinstance( prio, Priority ):
				prio = Priority( prio )
			if index == None:
				if not parent_hash in filecount_cache:
					filecount_cache[parent_hash] = len( self.file_list( parent_hash )[parent_hash] )
				for i in range( filecount_cache[parent_hash] ):
					args.append( "hash={}&p={}&f={}".format( url_quote( parent_hash ), url_quote( str( prio.value ) ), url_quote( str( i ) ) ) )
			else:
				args.append( "hash={}&p={}&f={}".format( url_quote( parent_hash ), url_quote( str( prio.value ) ), url_quote( str( index ) ) ) )
		self.do_action( "setprio", params_str = "&".join( args ) )

	def settings_get( self ):
		res = self.do_action( "getsettings" )
		out = {}
		for name, type, value in res["settings"]:
			out[name] = self._setting_val( type, value )
		return out

	def settings_set( self, settings ):
		args = []
		for k, v in settings.items():
			if isinstance( v, bool ):
				v = int( v )
			args.append( "s={}&v={}".format( url_quote( k ), url_quote( str( v ) ) ) )
		self.do_action( "setsetting", params_str = "&".join( args ) )

	def rss_list( self ):
		rss_feeds = {}
		self.torrent_list( rss_feeds = rss_feeds )
		return rss_feeds

	def rssfilter_list( self ):
		rss_filters = {}
		self.torrent_list( rss_filters = rss_filters )
		return rss_filters


class uTorrentFalcon( uTorrent ):

	_TorrentClass = Torrent_API2
	_JobInfoClass = JobInfo
	_FileClass = File_API2

	api_version = 1.9
	# no description yet, what I found out:
	# * no support for getversion

	def torrent_remove( self, torrents, with_data = False, with_torrent = False ):
		if with_data:
			if with_torrent:
				self.do_action( "removedatatorrent", { "hash" : self._get_hashes( torrents ) } )
			else:
				self.do_action( "removedata", { "hash" : self._get_hashes( torrents ) } )
		else:
			if with_torrent:
				self.do_action( "removetorrent", { "hash" : self._get_hashes( torrents ) } )
			else:
				self.do_action( "remove", { "hash" : self._get_hashes( torrents ) } )

	def torrent_remove_with_torrent( self, torrents ):
		return self.torrent_remove( torrents, False, True )

	def torrent_remove_with_data_torrent( self, torrents ):
		return self.torrent_remove( torrents, True, True )

	def file_get( self, file_hash, buffer, progress_cb = None ):
		parent_hash, index = self.parse_hash_prop( file_hash )
		self.do_action( "proxy", { "id" : parent_hash, "file" : index }, save_buffer = buffer, progress_cb = progress_cb )

	def settings_get( self, extended_attributes = False ):
		res = self.do_action( "getsettings" )
		out = {}
		for name, type, value, attrs in res["settings"]:
			out[name] = self._setting_val( type, value )
		return out

	def rss_add( self, url ):
		return self.rss_update( -1, { "url" : url } )

	def rss_update( self, feed_id, params ):
		params["feed-id"] = feed_id
		res = self.do_action( "rss-update", params )
		if "rss_ident" in res:
			return int( res["rss_ident"] )
		return feed_id

	def rss_remove( self, feed_id ):
		self.do_action( "rss-remove", { "feed-id" : feed_id } )

	def rssfilter_add( self, feed_id = -1 ):
		return self.rssfilter_update( -1, { "feed-id" : feed_id } )

	def rssfilter_update( self, filter_id, params ):
		params["filter-id"] = filter_id
		res = self.do_action( "filter-update", params )
		if "filter_ident" in res:
			return int( res["filter_ident"] )
		return filter_id

	def rssfilter_remove( self, filter_id ):
		self.do_action( "filter-remove", { "filter-id" : filter_id } )

	def xfer_history_get( self ):
		return self.do_action( "getxferhist" )["transfer_history"]

	def xfer_history_reset( self ):
		self.do_action( "resetxferhist" )


class uTorrentLinuxServer( uTorrentFalcon ):

	_pathmodule = posixpath

	api_version = 2 # http://download.utorrent.com/linux/utorrent-server-3.0-21886.tar.gz:bittorrent-server-v3_0/docs/uTorrent_Server.html

	def version( self ):
		if not self._version:
			self._version = Version( self.do_action( "getversion" ) )
		return self._version


if __name__ == "__main__":

	import optparse, sys

	level1 = "   "
	level2 = level1 * 2
	level3 = level1 * 3

	print_orig = print

	def print( *objs, sep = " ", end = "\n", file = sys.stdout ):
		global print_orig
		print_orig( *map( lambda x: str( x ).encode( sys.stdout.encoding, "replace" ).decode( sys.stdout.encoding ), objs ), sep = sep, end = end, file = file )

	def get_config_dir():
		config_home = os.getenv( "XDG_CONFIG_HOME" )
		if config_home == None:
			config_home = os.path.expanduser( "~" ) + os.path.sep + ".config"
		return config_home + os.path.sep + "utorrentctl" + os.path.sep

	def get_cache_dir():
		config_home = os.getenv( "XDG_CACHE_HOME" )
		if config_home == None:
			config_home = os.path.expanduser( "~" ) + os.path.sep + ".cache"
		return config_home + os.path.sep + "utorrentctl" + os.path.sep

	def dump_writer( obj, props, level1 = level2, level2 = level3 ):
		for name in sorted( props ):
			print( level1 + name, end = "" )
			try:
				value = getattr( obj, name )
				if is_list_type( value ):
					print( ":" )
					for item in value:
						if opts.verbose and hasattr( item, "verbose_str" ):
							item_str = item.verbose_str()
						else:
							item_str = str( item )
						print( level2 + item_str )
				else:
					if hasattr( obj, name + "_h" ):
						print( " = {} ({})".format( value, getattr( obj, name + "_h" ) ) )
					else:
						print( " = {}".format( value ) )
			except AttributeError:
				print()

	def filetree_writer( tree, cur_level = 0 ):
		for name, leaf in tree.items():
			if isinstance( leaf, dict ):
				print( level1 * cur_level + "+ " + name )
				filetree_writer( leaf, cur_level + 1 )
			else:
				print( level1 * cur_level + ( leaf.verbose_str() if opts.verbose else str( leaf ) ) )

	try:
		sys.path.append( get_config_dir() )
		from config import utorrentcfg
	except ImportError:
		utorrentcfg = { "host" : None, "login" : None, "password" : None }

	if not "api" in utorrentcfg:
		utorrentcfg["api"] = None

	if not "default_torrent_format" in utorrentcfg:
		utorrentcfg["default_torrent_format"] = None

	parser = optparse.OptionParser()
	parser.add_option( "-H", "--host", dest = "host", help = "host of uTorrent (hostname:port)" )
	parser.add_option( "-U", "--user", dest = "user", help = "WebUI login" )
	parser.add_option( "-P", "--password", dest = "password", help = "WebUI password" )
	parser.add_option( "--api", dest = "api", help = "Disable autodetection of server version and force specific API: linux, desktop (2.x), falcon (3.x)" )
	parser.add_option( "-n", "--nv", "--no-verbose", action = "store_false", dest = "verbose", default = True, help = "show shortened info in most cases (quicker, saves network traffic)" )
	parser.add_option( "--server-version", action = "store_const", dest = "action", const = "server_version", help = "print uTorrent server version" )
	parser.add_option( "-l", "--list-torrents", action = "store_const", dest = "action", const = "torrent_list", help = "list all torrents" )
	parser.add_option( "-c", "--active", action = "store_true", dest = "active", default = False, help = "when listing torrents display only active ones (speed > 0)" )
	parser.add_option( "-f", "--format", default = utorrentcfg["default_torrent_format"], dest = "format", help = "display torrent list in specific format, e.g. '{hash} {name} {ratio}', use --dump to view full list of available fields + peer_info (display seeds or peers depending on progress)" )
	parser.add_option( "--label", dest = "label", help = "when listing torrents display only ones with specified label" )
	parser.add_option( "-s", "--sort", default = "name", dest = "sort_field", help = "sort torrents, use --dump to view full list of available fields" )
	parser.add_option( "--desc", action = "store_true", dest = "sort_desc", default = False, help = "sort torrents in descending order" )
	parser.add_option( "-a", "--add-file", action = "store_const", dest = "action", const = "add_file", help = "add torrents specified by local file names, with force flag will force-start torrent after adding (filename filename ...)" )
	parser.add_option( "-u", "--add-url", action = "store_const", dest = "action", const = "add_url", help = "add torrents specified by urls, with force flag will force-start torrent after adding magnet url (url url ...)" )
	parser.add_option( "--dir", dest = "download_dir", help = "directory to download added torrent, absolute or relative to current download dir (for add, download)" )
	parser.add_option( "--settings", action = "store_const", dest = "action", const = "settings_get", help = "show current server settings, optionally you can use specific setting keys (name name ...)" )
	parser.add_option( "--set", action = "store_const", dest = "action", const = "settings_set", help = "assign settings value (key1=value1 key2=value2 ...)" )
	parser.add_option( "--start", action = "store_const", dest = "action", const = "torrent_start", help = "start torrents (hash hash ...)" )
	parser.add_option( "--stop", action = "store_const", dest = "action", const = "torrent_stop", help = "stop torrents (hash hash ...)" )
	parser.add_option( "--pause", action = "store_const", dest = "action", const = "torrent_pause", help = "pause torrents (hash hash ...)" )
	parser.add_option( "--resume", action = "store_const", dest = "action", const = "torrent_resume", help = "resume torrents (hash hash ...)" )
	parser.add_option( "--recheck", action = "store_const", dest = "action", const = "torrent_recheck", help = "recheck torrents, torrent will be stopped and restarted if needed (hash hash ...)" )
	parser.add_option( "--remove", action = "store_const", dest = "action", const = "torrent_remove", help = "remove torrents (hash hash ...)" )
	parser.add_option( "--all", action = "store_true", dest = "all", default = False, help = "applies action to all torrents/rss feeds (for start, stop, pause, resume, recheck, rss-update)" )
	parser.add_option( "-F", "--force", action = "store_true", dest = "force", default = False, help = "forces current command (for start, recheck (with all), remove, add-file, add-url, download)" )
	parser.add_option( "--data", action = "store_true", dest = "with_data", default = False, help = "when removing torrent also remove its data (for remove, also enabled by --force)" )
	parser.add_option( "--torrent", action = "store_true", dest = "with_torrent", default = False, help = "when removing torrent also remove its torrent file (for remove with uTorrent server, also enabled by --force)" )
	parser.add_option( "-i", "--info", action = "store_const", dest = "action", const = "torrent_info", help = "show info and file/trackers list for the specified torrents (hash hash ...)" )
	parser.add_option( "--dump", action = "store_const", dest = "action", const = "torrent_dump", help = "show full torrent info in key=value view (hash hash ...)" )
	parser.add_option( "--stats", action = "store_const", dest = "action", const = "stats", help = "display server download/upload statistics (uTorrent server only)" )
	parser.add_option( "--reset-stats", action = "store_const", dest = "action", const = "reset_stats", help = "reset server download/upload statistics (uTorrent server only)" )
	parser.add_option( "--download", action = "store_const", dest = "action", const = "download", help = "downloads specified file, with force flag will overwrite all existing files (hash.file_index)" )
	parser.add_option( "--prio", action = "store_const", dest = "action", const = "set_file_priority", help = "sets specified file priority, if you omit file_index then priority will be set for all files (hash[.file_index][=prio] hash[.file_index][=prio] ...) prio=0..3, if not specified then 2 is by default" )
	parser.add_option( "--set-props", action = "store_const", dest = "action", const = "set_props", help = "change properties of torrent, e.g. label; use --dump to view them (hash.prop=value hash.prop=value ...)" )
	parser.add_option( "--rss-list", action = "store_const", dest = "action", const = "rss_list", help = "list all rss feeds and filters" )
	parser.add_option( "--rss-add", action = "store_const", dest = "action", const = "rss_add", help = "add rss feeds specified by urls (feed_url feed_url ...)" )
	parser.add_option( "--rss-update", action = "store_const", dest = "action", const = "rss_update", help = "forces update of the specified rss feeds (feed_id feed_id ...)" )
	parser.add_option( "--rss-remove", action = "store_const", dest = "action", const = "rss_remove", help = "removes rss feeds specified by ids (feed_id feed_id ...)" )
	parser.add_option( "--rss-dump", action = "store_const", dest = "action", const = "rss_dump", help = "show full rss feed info in key=value view (feed_id feed_id ...)" )
	parser.add_option( "--rss-set-props", action = "store_const", dest = "action", const = "rss_set_props", help = "change properties of rss feed; use --rss-dump to view them (feed_id.prop=value feed_id.prop=value ...)" )
	parser.add_option( "--rssfilter-add", action = "store_const", dest = "action", const = "rssfilter_add", help = "add filters for specified rss feeds (feed_id feed_id ...)" )
	parser.add_option( "--rssfilter-remove", action = "store_const", dest = "action", const = "rssfilter_remove", help = "removes rss filter specified by ids (filter_id filter_id ...)" )
	parser.add_option( "--rssfilter-dump", action = "store_const", dest = "action", const = "rssfilter_dump", help = "show full rss filter info in key=value view (filter_id filter_id ...)" )
	parser.add_option( "--rssfilter-set-props", action = "store_const", dest = "action", const = "rssfilter_set_props", help = "change properties of rss filter; use --rssfilter-dump to view them (filter_id.prop=value filter_id.prop=value ...)" )
	parser.add_option( "--magnet", action = "store_const", dest = "action", const = "get_magnet", help = "generate magnet link for the specified torrents (hash hash ...)" )
	opts, args = parser.parse_args()

	try:

		if opts.host == None: # we didn't supply host in command line => load auth data from config
			opts.host = utorrentcfg["host"]
			if opts.user == None:
				opts.user = utorrentcfg["login"]
			if opts.password == None:
				opts.password = utorrentcfg["password"]
			if opts.api == None:
				opts.api = utorrentcfg["api"]

		if opts.action != None:
			utorrent = uTorrentConnection( opts.host, opts.user, opts.password ).utorrent( opts.api )

		if opts.action == "server_version":
			print( utorrent.version().verbose_str() if opts.verbose else utorrent.version() )

		elif opts.action == "torrent_list":
			total_ul, total_dl, count, total_size = 0, 0, 0, 0
			opts.sort_field = opts.sort_field.lower()
			if not opts.sort_field in utorrent.TorrentClass.get_public_attrs() + utorrent.TorrentClass.get_readonly_attrs():
				opts.sort_field = "name"
			for h, t in sorted( utorrent.torrent_list().items(), key = lambda x: getattr( x[1], opts.sort_field ), reverse = opts.sort_desc ):
				if not opts.active or opts.active and ( t.ul_speed > 0 or t.dl_speed > 0 ): # handle --active
					if opts.label == None or opts.label == t.label: # handle --label
						count += 1
						total_size += t.progress / 100 * t.size
						if opts.verbose:
							print( t.verbose_str( opts.format ) )
							total_ul += t.ul_speed
							total_dl += t.dl_speed
						else:
							print( t )
			if opts.verbose:
				print( "Total speed: D:{}/s U:{}/s  count: {}  size: {}".format(
					uTorrent.human_size( total_dl ), uTorrent.human_size( total_ul ),
					count, uTorrent.human_size( total_size )
				) )

		elif opts.action == "add_file":
			for i in args:
				print( "Submitting {}...".format( i ) )
				hsh = utorrent.torrent_add_file( i, opts.download_dir )
				print( level1 + "Info hash = {}".format( hsh ) )
				if opts.force:
					print( level1 + "Forcing start..." )
					utorrent.torrent_start( hsh, True )

		elif opts.action == "add_url":
			for i in args:
				print( "Submitting {}...".format( i ) )
				hsh = utorrent.torrent_add_url( i, opts.download_dir )
				if hsh != None:
					print( level1 + "Info hash = {}".format( hsh ) )
					if opts.force:
						print( level1 + "Forcing start..." )
						utorrent.torrent_start( hsh, True )

		elif opts.action == "settings_get":
			for i in sorted( utorrent.settings_get().items() ):
				if len( args ) == 0 or i[0] in args:
					print( "{} = {}".format( *i ) )

		elif opts.action == "settings_set":
			utorrent.settings_set( { k : v for k, v in [ i.split( "=" ) for i in args] } )

		elif opts.action == "torrent_start":
			torr_list = None
			if opts.all:
				torr_list = utorrent.torrent_list()
				args = torr_list.keys()
				print( "Starting all torrents..." )
			else:
				if opts.verbose:
					torrs = utorrent.resolve_torrent_hashes( args, torr_list )
				else:
					torrs = args
				print( "Starting " + ", ".join( torrs ) + "..." )
			utorrent.torrent_start( args, opts.force )

		elif opts.action == "torrent_stop":
			torr_list = None
			if opts.all:
				torr_list = utorrent.torrent_list()
				args = torr_list.keys()
				print( "Stopping all torrents..." )
			else:
				if opts.verbose:
					torrs = utorrent.resolve_torrent_hashes( args, torr_list )
				else:
					torrs = args
				print( "Stopping " + ", ".join( torrs ) + "..." )
			utorrent.torrent_stop( args )

		elif opts.action == "torrent_resume":
			torr_list = None
			if opts.all:
				torr_list = utorrent.torrent_list()
				args = torr_list.keys()
				print( "Resuming all torrents..." )
			else:
				if opts.verbose:
					torrs = utorrent.resolve_torrent_hashes( args, torr_list )
				else:
					torrs = args
				print( "Resuming " + ", ".join( torrs ) + "..." )
			utorrent.torrent_resume( args )

		elif opts.action == "torrent_pause":
			torr_list = None
			if opts.all:
				torr_list = utorrent.torrent_list()
				args = torr_list.keys()
				print( "Pausing all torrents..." )
			else:
				if opts.verbose:
					torrs = utorrent.resolve_torrent_hashes( args, torr_list )
				else:
					torrs = args
				print( "Pausing " + ", ".join( torrs ) + "..." )
			utorrent.torrent_pause( args )

		elif opts.action == "torrent_recheck":
			torr_list = utorrent.torrent_list()
			if opts.all:
				if opts.force:
					args = torr_list.keys()
					print( "Rechecking all torrents..." )
				else:
					raise uTorrentError( "Refusing to recheck all torrents! Please specify --force to override" )
			else:
				if opts.verbose:
					torrs = utorrent.resolve_torrent_hashes( args, torr_list )
				else:
					torrs = args
				print( "Rechecking " + ", ".join( torrs ) + "..." )
			for hsh in args:
				if hsh in torr_list:
					torr = torr_list[hsh]
					torr.stop()
					torr.recheck()
					if ( torr.status.started and not torr.status.paused ) or torr.status.error:
						torr.start( not( torr.status.queued or torr.status.error ) )

		elif opts.action == "torrent_remove":
			if opts.verbose:
				torrs = utorrent.resolve_torrent_hashes( args )
			else:
				torrs = args
			print( "Removing " + ", ".join( torrs ) + "..." )
			if utorrent.api_version == uTorrentLinuxServer.api_version:
				utorrent.torrent_remove( args, opts.with_data or opts.force, opts.with_torrent or opts.force )
			else:
				utorrent.torrent_remove( args, opts.with_data or opts.force )

		elif opts.action == "torrent_info":
			tors = utorrent.torrent_list()
			files = utorrent.file_list( args )
			infos = utorrent.torrent_info( args )
			for hsh, fls in files.items():
				print( tors[hsh].verbose_str( opts.format ) if opts.verbose else tors[hsh] )
				print( level1 + ( infos[hsh].verbose_str() if opts.verbose else str( infos[hsh] ) ) )
				print( level1 + "Files ({}):".format( len( fls ) ) )
				for f in fls:
					print( level2 + ( f.verbose_str() if opts.verbose else str( f ) ) )
				print( level1 + "Trackers:" )
				for tr in infos[hsh].trackers:
					print( level2 + tr )

		elif opts.action == "torrent_dump":
			tors = utorrent.torrent_list()
			infos = utorrent.torrent_info( args )
			for hsh, info in infos.items():
				print( tors[hsh].verbose_str( opts.format ) if opts.verbose else tors[hsh] )
				print( level1 + "Properties:" )
				dump_writer( tors[hsh], tors[hsh].get_public_attrs() )
				dump_writer( info, info.get_public_attrs() )
				print( level1 + "Read-only:" )
				dump_writer( tors[hsh], tors[hsh].get_readonly_attrs() )

		elif opts.action == "stats":
			res = utorrent.xfer_history_get()
			excl_local = utorrent.settings_get()["net.limit_excludeslocal"]
			torrents = utorrent.torrent_list()
			today_start = datetime.datetime.now().replace( hour = 0, minute = 0, second = 0, microsecond = 0 )
			period = len( res["daily_download"] )
			period_start = today_start - datetime.timedelta( days = period - 1 )

			down_total_local = sum( res["daily_local_download"] )
			down_total = sum( res["daily_download"] ) - ( down_total_local if excl_local else 0 )
			up_total_local = sum( res["daily_local_upload"] )
			up_total = sum( res["daily_upload"] ) - ( down_total_local if excl_local else 0 )
			period_added_torrents = { k : v for k, v in torrents.items() if v.added_on >= period_start }
			period_completed_torrents = { k : v for k, v in torrents.items() if v.completed_on >= period_start }
			print( "Last {} days:".format( period ) )
			print( level1 + "Downloaded: {} (+{} local)".format( uTorrent.human_size( down_total ), uTorrent.human_size( down_total_local ) ) )
			print( level1 + "  Uploaded: {} (+{} local)".format( uTorrent.human_size( up_total ), uTorrent.human_size( up_total_local ) ) )
			print( level1 + "     Total: {} (+{} local)".format( uTorrent.human_size( down_total + up_total ), uTorrent.human_size( down_total_local + up_total_local ) ) )
			print( level1 + "Ratio: {:.2f}".format( up_total / down_total ) )
			print( level1 + "Added torrents: {}".format( len( period_added_torrents ) ) )
			print( level1 + "Completed torrents: {}".format( len( period_completed_torrents ) ) )

			down_day_local = res["daily_local_download"][0]
			down_day = res["daily_download"][0] - ( down_day_local if excl_local else 0 )
			up_day_local = res["daily_local_upload"][0]
			up_day = res["daily_upload"][0] - ( up_day_local if excl_local else 0 )
			today_added_torrents = { k : v for k, v in torrents.items() if v.added_on >= today_start }
			today_completed_torrents = { k : v for k, v in torrents.items() if v.completed_on >= today_start }
			print( "Today:" )
			print( level1 + "Downloaded: {} (+{} local)".format( uTorrent.human_size( down_day ), uTorrent.human_size( down_day_local ) ) )
			print( level1 + "  Uploaded: {} (+{} local)".format( uTorrent.human_size( up_day ), uTorrent.human_size( up_day_local ) ) )
			print( level1 + "     Total: {} (+{} local)".format( uTorrent.human_size( down_day + up_day ), uTorrent.human_size( down_day_local + up_day_local ) ) )
			print( level1 + "Ratio: {:.2f}".format( up_day / down_day ) )
			print( level1 + "Added torrents: {}".format( len( today_added_torrents ) ) )
			print( level1 + "Completed torrents: {}".format( len( today_completed_torrents ) ) )

		elif opts.action == "reset_stats":
			res = utorrent.xfer_history_reset()

		elif opts.action == "download":
			if utorrent.api_version < uTorrentFalcon.api_version:
				raise uTorrentError( "Downloading files only supported for uTorrent 3.x and uTorrent Server" )
			for filespec in args:
				parent_hash, indices = uTorrent.parse_hash_prop( filespec )
				files = utorrent.file_list( parent_hash )
				if len( files ) == 0:
					print( "Specified torrent or file does not exist" )
					sys.exit( 1 )
				base_dir = opts.download_dir if opts.download_dir else "."
				make_tree = False # single file download => place it in the base directory
				torrents = None
				if indices == None:
					indices = [ i for i, f in enumerate( files[parent_hash] ) if f.progress == 100 and f.priority.value > 0 ]
					if len( files[parent_hash] ) > 1:
						make_tree = True # whole torrent download => keep directory tree
					torrents = utorrent.torrent_list()
				else:
					indices = ( int( indices ), )

				def progress( loaded, total ):
					global bar_width, increm, start_time
					progr = round( loaded / increm ) if increm > 0 else 1
					delta = datetime.datetime.now() - start_time
					delta = delta.seconds + delta.microseconds / 1000000
					if opts.verbose:
						print( "[{}{}] {} {}/s eta: {}{}".format(
							"*" * progr, "_" * ( bar_width - progr ),
							uTorrent.human_size( total ),
							uTorrent.human_size( loaded / delta ),
							uTorrent.human_time_delta( ( total - loaded ) / ( loaded / delta ) if loaded > 0 else 0 ),
							" " * 25
							), sep = "", end = ""
						)
						print( "\b" * ( bar_width + 70 ), end = "" )
						sys.stdout.flush()

				for index in indices:
					if make_tree:
						filename = base_dir + os.path.sep + torrents[parent_hash].name + os.path.sep + os.path.normpath( files[parent_hash][index].name )
					else:
						filename = base_dir + os.path.sep + utorrent.pathmodule.basename( files[parent_hash][index].name )
					if os.path.exists( filename ) and not opts.force:
						print( "Skipping {}, already exists, specify --force to overwrite...".format( filename ) )
					else:
						try:
							os.makedirs( os.path.dirname( filename ) )
						except OSError as e:
							if( e.args[0] != 17 ): # "File exists" => dir exists, by design, ignore
								raise e
						print( "Downloading {}...".format( filename ) )
						file = open( filename, "wb" )
						bar_width = 50
						increm = files[parent_hash][index].size / bar_width
						start_time = datetime.datetime.now()
						utorrent.file_get( "{}.{}".format( parent_hash, index ), buffer = file, progress_cb = progress )
						if opts.verbose:
							print( "" )

		elif opts.action == "set_file_priority":
			prios = {}
			for i in args:
				parts = i.split( "=" )
				if len( parts ) == 2:
					prios[parts[0]] = parts[1]
				else:
					prios[parts[0]] = "2"
			utorrent.file_set_priority( prios )

		elif opts.action == "set_props":
			props = []
			for a in args:
				hsh, value = a.split( "=", 1 )
				hsh, name = hsh.split( ".", 1 )
				props.append( { hsh : { name : value } } )
			utorrent.torrent_set_props( props )

		elif opts.action == "rss_list":
			rssfeeds = {}
			rssfilters = {}
			utorrent.torrent_list( None, rssfeeds, rssfilters )
			feed_id_index = {}
			for filter_id, filter_props in rssfilters.items():
				if not filter_props.feed_id in feed_id_index:
					feed_id_index[filter_props.feed_id] = []
				feed_id_index[filter_props.feed_id].append( filter_props )
			print( "Feeds:" )
			for feed_id, feed in rssfeeds.items():
				print( level1 + ( feed.verbose_str() if opts.verbose else str( feed ) ) )
				if feed_id in feed_id_index:
					print( level1 + "Filters:" )
					for filter_props in feed_id_index[feed_id]:
						print( level2 + ( filter_props.verbose_str() if opts.verbose else str( filter_props ) ) )
			if -1 in feed_id_index and len( feed_id_index[-1] ) > 0:
				print( "Global filters:" )
				for filter_props in feed_id_index[-1]:
					print( level1 + ( filter_props.verbose_str() if opts.verbose else str( filter_props ) ) )

		elif opts.action == "rss_add":
			for url in args:
				print( "Adding {}...".format( url ) )
				feed_id = utorrent.rss_add( url )
				if feed_id != -1:
					print( level1 + "Feed id = {} (add a filter to it to make it download something)".format( feed_id ) )
				else:
					print( level1 + "Failed to add feed" )

		elif opts.action == "rss_update":
			feed_list = None
			if opts.all:
				feed_list = utorrent.rss_list()
				args = list( map( str, feed_list.keys() ) )
				print( "Updating all rss feeds..." )
			else:
				if opts.verbose:
					feeds = utorrent.resolve_feed_ids( args, feed_list )
				else:
					feeds = args
				print( "Updating " + ", ".join( feeds ) + "..." )
			for feed_id in args:
				utorrent.rss_update( feed_id, { "update" : 1 } )

		elif opts.action == "rss_remove":
			if opts.verbose:
				feeds = utorrent.resolve_feed_ids( args )
			else:
				feeds = args
			print( "Removing " + ", ".join( feeds ) + "..." )
			for feed_id in args:
				utorrent.rss_remove( feed_id )

		elif opts.action == "rss_dump":
			feeds = utorrent.rss_list()
			for feed_id, feed in { i : f for i, f in feeds.items() if str( i ) in args }.items():
				print( feed.url )
				print( level1 + "Properties:" )
				dump_writer( feed, feed.get_public_attrs() )
				print( level1 + "Read-only:" )
				dump_writer( feed, feed.get_readonly_attrs() )
				print( level1 + "Write-only:" )
				dump_writer( feed, feed.get_writeonly_attrs() )

		elif opts.action == "rss_set_props":
			for a in args:
				feed_id, value = a.split( "=", 1 )
				feed_id, name = feed_id.split( ".", 1 )
				if name in RssFeed.get_public_attrs() or name in RssFeed.get_writeonly_attrs():
					utorrent.rss_update( feed_id, { name : value } )

		elif opts.action == "rssfilter_add":
			for feed_id in args:
				print( "Adding filter for feed {}...".format( feed_id ) )
				filter_id = utorrent.rssfilter_add( feed_id )
				if filter_id != -1:
					print( level1 + "Filter id = {}".format( filter_id ) )
				else:
					print( level1 + "Failed to add filter" )

		elif opts.action == "rssfilter_remove":
			if opts.verbose:
				feeds = utorrent.resolve_filter_ids( args )
			else:
				feeds = args
			print( "Removing " + ", ".join( feeds ) + "..." )
			for filter_id in args:
				utorrent.rssfilter_remove( filter_id )

		elif opts.action == "rssfilter_dump":
			filters = utorrent.rssfilter_list()
			for filter_id, filter_props in { i : f for i, f in filters.items() if str( i ) in args }.items():
				print( filter_props.name )
				print( level1 + "Properties:" )
				dump_writer( filter_props, filter_props.get_public_attrs() )
				print( level1 + "Read-only:" )
				dump_writer( filter_props, filter_props.get_readonly_attrs() )
				print( level1 + "Write-only:" )
				dump_writer( filter_props, filter_props.get_writeonly_attrs() )

		elif opts.action == "rssfilter_set_props":
			for a in args:
				filter_id, value = a.split( "=", 1 )
				filter_id, name = filter_id.split( ".", 1 )
				if name in RssFilter.get_public_attrs() or RssFilter.get_writeonly_attrs():
					utorrent.rssfilter_update( filter_id, { name.replace( "_", "-" ) : value } )

		elif opts.action == "get_magnet":
			if opts.verbose:
				tors = utorrent.torrent_list()
			for hsh, lnk in utorrent.torrent_get_magnet( args ).items():
				print( tors[hsh] if opts.verbose else hsh )
				print( level1 + lnk )

		else:
			parser.print_help()

	except uTorrentError as e:
		print( e )
		sys.exit( 1 )
