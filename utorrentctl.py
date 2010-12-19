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

import urllib.request, http.client, http.cookiejar, urllib.parse, socket
import base64, posixpath, ntpath, email.generator, os.path, datetime, errno
from hashlib import sha1
import re, json, itertools 
def url_quote( string ):
	return urllib.parse.quote( string, "" )
try:
	from config import utorrentcfg
except ImportError:
	utorrentcfg = { "host" : None, "login" : None, "password" : None  }


def bdecode( data, str_encoding = "utf8" ):
	if not hasattr( data, "__next__" ):
		data = iter( data )
	out = None
	t = chr( next( data ) )
	if t == "e":
		return None
	elif t == "i":
		out = ""
		c = chr( next( data ) )
		while c != "e":
			out += c
			c = chr( next( data ) )
		out = int( out )
	elif t == "l":
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
	elif t in( list, tuple ):
		out.extend( b"l" )
		for e in map( bencode, obj ):
			out.extend( e )
		out.extend( b"e" )
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
	else:
		obj = str( obj ).encode( str_encoding )
		out.extend( str( len( obj ) ).encode( str_encoding ) )
		out.extend( b":" )
		out.extend( obj )
	return bytes( out )


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
		else:
			# fill some partially made up values as desktop client doesn't provide full info, only build
			self.product = "desktop"
			self.build = self.engine = self.ui = res["build"]
			build_versions = ( ( 23217, 3, 0, 0 ), ( 23071, 2, 2, 0 ), ( 0, 2, 0, 4 ) )
			for version in build_versions:
				if self.build >= version[0]:
					self.major, self.middle, self.minor = version[1:]
					break
			self.user_agent = "BTWebClient/{}{}{}0({})".format( self.major, self.middle, self.minor, self.build )
			self.peer_id = "UT{}{}{}0".format( self.major, self.middle, self.minor )

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
	queued = False
	loaded = False

	def __init__( self, status, percent_loaded = 0 ):
		self._value = status
		self._progress = percent_loaded
		self.started = status & 1
		self.checking = status & 2
		self.start_after_check = status & 4
		self.checked = status & 8
		self.error = status & 16
		self.paused = status & 32
		self.queued = status & 64
		self.loaded = status & 128

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
	queue_order = 0
	dl_remain = 0

	def __init__( self, utorrent, torrent = None ):
		self._utorrent = utorrent
		if torrent:
			self.fill( torrent )

	def __str__( self ):
		return "{} {}".format( self.hash, self.name )

	def verbose_str( self ):
		return "{} {: <15} {: >5.1f}% {: >9} D:{: >14} U:{: >14} {: <8.3f} {: <9} eta: {: <7} {}{}".format(
			self.hash, self.status, self.progress, self.size_h,
			self.dl_speed_h if self.dl_speed > 0 else "", self.ul_speed_h if self.ul_speed > 0 else "",
			self.ratio, "{}({})/{}".format( self.seeds_connected, self.seeds_total, self.peers_connected ),
			self.eta_h, self.name, " ({})".format( self.label ) if self.label else ""
		)

	def dump( self ):
		return { k : str( getattr( self, k ) ) for k in self.get_sortable_attrs() }

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

	@classmethod
	def get_sortable_attrs( cls ):
		return [ i for i in dir( cls ) if not re.search( "^_|_h$", i ) and not hasattr( getattr( cls, i ), "__call__" ) ]

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

	def fill( self, torrent ):
		Torrent.fill( self, torrent[0:19] )
		self.url, self.rss_url, self.status_message, self._unk_hash = torrent[19:]
	
	def remove( self, with_data = False, with_torrent = False ):
		return self._utorrent.torrent_remove( self, with_data, with_torrent )


class Torrent_API1_9( Torrent_API2 ):

	added_on = 0
	_unk_num = 0
	_unk_str = 0

	def fill( self, torrent ):
		Torrent_API2.fill( self, torrent[0:23] )
		self.added_on, self._unk_num, self._unk_str = torrent[23:]
		self.added_on = datetime.datetime.fromtimestamp( self.added_on )


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
		return "{: <44} [{: <15}] {: >5}% ({: >9} / {: >9}) {}".format( self.hash, self.priority, self.progress, self.downloaded_h, self.size_h, self.name )

	def fill( self, file ):
		self.name, self.size, self.downloaded, priority = file
		self.priority = Priority( priority )
		if self.size == 0:
			self.progress = 100
		else:
			self.progress = round( float( self.downloaded ) / self.size * 100, 1 )
		self.size_h = uTorrent.human_size( self.size )
		self.downloaded_h = uTorrent.human_size( self.downloaded )

	def set_priority( self, priority ):
		self._utorrent.file_set_priority( { self.hash : priority } )


class File_API1_9( File ):

	def fill( self, file ):
		File.fill( self, file[:4] )


class JobInfo_API1_9:

	_utorrent = None

	hash = ""
	trackers = []
	ulrate = 0
	dlrate = 0
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
		return "Limits D:{} U:{};  Superseed:{};  DHT:{};  PEX:{};  Queuing override:{}  Seed ratio:{};  Seed time:{}".format(
			self.dlrate, self.ulrate, self._tribool_status_str( self.superseed ), self._tribool_status_str( self.dht ),
			self._tribool_status_str( self.pex ), self._tribool_status_str( self.seed_override ), self.seed_ratio,
			uTorrent.human_time_delta( self.seed_time )
		)

	def dump( self ):
		return { k : str( getattr( self, k ) ) for k in self.get_sortable_attrs() }

	def fill( self, jobinfo ):
		self.hash = jobinfo["hash"]
		self.trackers = jobinfo["trackers"].strip().split( "\r\n\r\n" )
		self.ulrate = jobinfo["ulrate"]
		self.dlrate = jobinfo["dlrate"]
		self.superseed = jobinfo["superseed"]
		self.dht = jobinfo["dht"]
		self.pex = jobinfo["pex"]
		self.seed_override = jobinfo["seed_override"]
		self.seed_ratio = jobinfo["seed_ratio"]
		self.seed_time = jobinfo["seed_time"]

	@classmethod
	def get_sortable_attrs( cls ):
		return [ i for i in dir( cls ) if not re.search( "^_|_h$", i ) and not hasattr( getattr( cls, i ), "__call__" ) ]

	def _tribool_status_str( self, status ):
		return "not allowed" if status == -1 else ( "disabled" if status == 0 else "enabled" )


class JobInfo( JobInfo_API1_9 ):

	ulslots = 0

	def verbose_str( self ):
		return "{};  Upload slots:{}".format( JobInfo_API1_9.verbose_str( self ), self.ulslots ) 

	def fill( self, jobinfo ):
		JobInfo_API1_9.fill( self, jobinfo )
		self.ulslots = jobinfo["ulslots"]


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

	def _get_data( self, loc, data = None, retry = True, save_to_file = None, progress_cb = None ):
		last_e = None
		utserver_retries = 0
		retries = 0
		max_retries = self._retry_max if retry else 1
		while retries < max_retries or utserver_retries == 1:
			try:
				headers = { k : v for k, v in self._request.header_items() }
				if data:
					bnd = email.generator._make_boundary()
					headers["Content-Type"] = "multipart/form-data; boundary={}".format( bnd )
					data = data.replace( "{{BOUNDARY}}", bnd )
				self._request.add_data( data )
				self.request( self._request.get_method(), self._request.get_selector() + loc, self._request.get_data(), headers )
				resp = self.getresponse()
				if save_to_file:
					read = 0
					resp_len = resp.length
					while True:
						buf = resp.read( 10240 )
						read += len( buf )
						if progress_cb:
							progress_cb( read, resp_len )
						if len( buf ) == 0:
							break
						save_to_file.write( buf )
					return None
				out = resp.read().decode( "utf8" )
				if resp.status == 400:
					last_e = uTorrentError( out.strip() )
					# if uTorrent server alpha is bound to the same port as WebUI then it will respond with "invalid request" to the first request in the connection
					if ( not self._utorrent or type( self._utorrent ) == uTorrentLinuxServer ) and utserver_retries == 0:
						utserver_retries += 1
						continue
					raise last_e
				elif resp.status == 404 or resp.status == 401:
					raise uTorrentError( resp.reason )
				elif resp.status != 200:
					raise uTorrentError( "{}: {}".format( resp.reason, resp.status ) )
				self._cookies.extract_cookies( resp, self._request )
				if len( self._cookies ) > 0:
					self._request.add_header( "Cookie", "; ".join( [ "{}={}".format( url_quote( c.name ), url_quote( c.value ) ) for c in self._cookies ] ) )
				return out
			except socket.gaierror as e:
				raise uTorrentError( e.args[1] )
			except socket.error as e:
				e = e.args[0]
				if str( e ) == "timed out":
					last_e = uTorrentError( "Timeout" )
				elif e.args[0] == errno.ECONNREFUSED:
					self.close()
					raise uTorrentError( e.args[1] )
			except ( http.client.CannotSendRequest, http.client.BadStatusLine ) as e:
				self.close()
				raise e
			retries += 1
		if last_e:
			self.close()
			raise last_e

	def _fetch_token( self ):
		data = self._get_data( "gui/token.html" )
		match = re.search( "<div .*?id='token'.*?>(.+?)</div>", data )
		if match == None:
			raise uTorrentError( "Can't fetch security token" )
		self._token = match.group( 1 )

	def _action( self, action, params = None, params_str = None ):
		args = []
		if params:
			for k, v in params.items():
				if isinstance( v, ( tuple, list ) ):
					for i in v:
						args.append( "{}={}".format( url_quote( str( k ) ), url_quote( str( i ) ) ) )
				else:
					args.append( "{}={}".format( url_quote( str( k ) ), url_quote( str( v ) ) ) )
		if params_str:
			params_str = "&" + params_str
		else:
			params_str = ""
		if action == "list":
			args.insert( 0, "token=" + url_quote( self._token ) )
			args.insert( 1, "list=1" )
			section = "gui/"
		elif action == "proxy":
			section = "proxy"
		else:
			args.insert( 0, "token=" + url_quote( self._token ) )
			args.insert( 1, "action=" + url_quote( str( action ) ) )
			section = "gui/"
		return section + "?" + "&".join( args ) + params_str

	def do_action( self, action, params = None, params_str = None, data = None, retry = True, save_to_file = None, progress_cb = None ):
		# uTorrent can send incorrect overlapping array objects, this will fix them, converting them into list
		def obj_hook( obj ):
			out = {}
			for k, v in obj:
				if k in out:
					out[k].extend( v )
				else:
					out[k] = v
			return out
		res = self._get_data( self._action( action, params, params_str ), data = data, retry = retry, save_to_file = save_to_file, progress_cb = progress_cb )
		if res:
			return json.loads( res, object_pairs_hook = obj_hook )
		else:
			return ""

	def utorrent( self ):
		try:
			ver = Version( self.do_action( "getversion", retry = False ) )
		except http.client.BadStatusLine:
			return uTorrent( self )
		except uTorrentError as e:
			if e.args[0] == "invalid request":
				return uTorrentFalcon( self )
		if ver.product == "server":
			return uTorrentLinuxServer( self, ver )
		else:
			raise uTorrentError( "Unsupported WebAPI" )


class uTorrent:

	_url = ""

	_connection = None
	_version = None

	_TorrentClass = Torrent
	_JobInfoClass = JobInfo
	_FileClass = File

	_pathmodule = ntpath
	
	_list_cache = None
	_list_cache_id = 0

	api_version = 1 # http://forum.utorrent.com/viewtopic.php?id=25661

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
	def _setting_val( type, value ):
		# Falcon incorrectly sends type 0 and empty string for some fields (e.g. boss_pw and boss_key_salt)
		if type == 0 and value != '': # int
			return int( value )
		elif type == 1 and value != '': # bool
			return value == "true"
		else:
			return value

	@staticmethod
	def human_size( size, suffixes = ( "B", "kiB", "MiB", "GiB", "TiB" ) ):
		for s in suffixes:
			if size < 1024:
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
	def is_hash( hash ):
		return re.match( "[0-9A-F]{40}$", hash, re.IGNORECASE )

	@staticmethod
	def get_info_hash( torrent_data ):
		return sha1( bencode( bdecode( torrent_data )["info"] ) ).hexdigest().upper()

	@classmethod
	def check_hash( cls, hash ):
		if not cls.is_hash( hash ):
			raise uTorrentError( "Incorrect hash: {}".format( hash ) )

	@classmethod
	def parse_hash_prop( cls, hash_prop ):
		if isinstance( hash_prop, ( File, Torrent, JobInfo_API1_9 ) ):
			hash_prop = hash_prop.hash
		try:
			parent_hash, prop = hash_prop.split( ".", 1 )
		except ValueError:
			parent_hash, prop = hash_prop, None
		parent_hash = parent_hash.upper()
		cls.check_hash( parent_hash )
		return parent_hash, prop

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
		if not hasattr( torrents, "__iter__" ) or isinstance( torrents, str ):
			torrents = ( torrents, )
		out = []
		for t in torrents:
			if isinstance( t, self._TorrentClass ):
				hash = t.hash
			elif isinstance( t, str ):
				hash = t
			else:
				raise uTorrentError( "Hash designation only supported via Torrent class or string" )
			self.check_hash( hash )
			out.append( hash )
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

	def do_action( self, action, params = None, params_str = None, data = None, retry = True, save_to_file = None, progress_cb = None ):
		return self._connection.do_action( action = action, params = params, params_str = params_str, data = data, retry = retry, save_to_file = save_to_file, progress_cb = progress_cb )

	def version( self ):
		if not self._version:
			self._version = Version( self.do_action( "start" ) )
		return self._version

	def torrent_list( self, labels = None ):
		if self._list_cache_id:
			res = self.do_action( "list", { "cid" : self._list_cache_id } )
			for t in res["torrentm"]:
				del self._list_cache[t]
			for t in res["torrentp"]:
				self._list_cache[t[0]] = self._TorrentClass( self, t )
		else:
			res = self.do_action( "list" )
			self._list_cache = { hash : torrent for hash, torrent in [ ( i[0], self._TorrentClass( self, i ) ) for i in res["torrents"] ] }
		self._list_cache_id = res["torrentc"]
		if labels != None:
			labels.extend( [ Label( i ) for i in res["label"] ] )
#		if rss_feeds != None:
#			rss_feeds.extend( res["rssfeeds"] )
#		if rss_filters != None:
#			rss_filters.extend( res["rssfilters"] )
		return self._list_cache

	def torrent_info( self, torrents ):
		res = self.do_action( "getprops", { "hash" : self._get_hashes( torrents ) } )
		if not "props" in res:
			return {}
		return { hash : info for hash, info in [ ( i["hash"], self._JobInfoClass( self, jobinfo = i ) ) for i in res["props"] ] }

	def torrent_add_url( self, url, download_dir = None ):
		prev_dir = self._handle_download_dir( download_dir )
		res = self.do_action( "add-url", { "s" : url } );
		self._handle_prev_dir( prev_dir )
		if "error" in res:
			raise uTorrentError( res["error"] )

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
			for hash in fi:
				out[hash] = [ self._FileClass( self, hash, i, f ) for i, f in enumerate( next( fi ) ) ]
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


class uTorrentFalcon( uTorrent ):

	_TorrentClass = Torrent_API1_9
	_JobInfoClass = JobInfo_API1_9
	_FileClass = File_API1_9

	api_version = 1.9
	# no description yet, what I found out:
	# * no support for getversion
	# * additional fields in Torrent (e.g. added on)
	# * additional fields in File
	# * no ulslots in job info
	# * settings are received in APIv2 format with additional access field

	def settings_get( self, extended_attributes = False ):
		res = self.do_action( "getsettings" )
		out = {}
		for name, type, value, attrs in res["settings"]:
			out[name] = self._setting_val( type, value )
		return out


class uTorrentLinuxServer( uTorrent ):

	_TorrentClass = Torrent_API2

	_pathmodule = posixpath

	api_version = 2 # http://download.utorrent.com/linux/utorrent-server-3.0-21886.tar.gz:bittorrent-server-v3_0/docs/uTorrent_Server.html

	def version( self ):
		if not self._version:
			self._version = Version( self.do_action( "getversion" ) )
		return self._version

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
		self.do_action( "proxy", { "id" : parent_hash, "file" : index }, save_to_file = buffer, progress_cb = progress_cb )

	def settings_get( self, extended_attributes = False ):
		res = self.do_action( "getsettings" )
		out = {}
		for name, type, value, attrs in res["settings"]:
			out[name] = self._setting_val( type, value )
		return out


if __name__ == "__main__":

	import optparse, sys

	print_orig = print

	def print( *objs, sep = " ", end = "\n", file = sys.stdout ):
		global print_orig
		print_orig( *map( lambda x: str( x ).encode( sys.stdout.encoding, "replace" ).decode( sys.stdout.encoding ), objs ), sep = sep, end = end, file = file )

	level1 = "\t"
	level2 = "\t" * 2
	
	parser = optparse.OptionParser()
	parser.add_option( "-H", "--host", dest = "host", default = utorrentcfg["host"], help = "host of uTorrent (hostname:port)" )
	parser.add_option( "-U", "--user", dest = "user", default = utorrentcfg["login"], help = "WebUI login" )
	parser.add_option( "-P", "--password", dest = "password", default = utorrentcfg["password"], help = "WebUI password" )
	parser.add_option( "--nv", "--no-verbose", action = "store_false", dest = "verbose", default = True, help = "show shortened info in most cases (quicker, saves network traffic)" )
	parser.add_option( "--server-version", action = "store_const", dest = "action", const = "server_version", help = "print uTorrent server version" )
	parser.add_option( "-l", "--list-torrents", action = "store_const", dest = "action", const = "torrent_list", help = "list all torrents" )
	parser.add_option( "-c", "--active", action = "store_true", dest = "active", default = False, help = "when listing torrents display only active ones (speed > 0)" )
	parser.add_option( "--label", dest = "label", help = "when listing torrents display only ones with specified label" )
	parser.add_option( "-s", "--sort", default = "name", dest = "sort_field", help = "sort torrents, values are: availability, dl_remain, dl_speed, downloaded, eta, hash, label, name, peers_connected, peers_total, progress, queue_order, ratio, seeds_connected, seeds_total, size, status, ul_speed, uploaded; +server: url, rss_url; +falcon: added_on" )
	parser.add_option( "--desc", action = "store_true", dest = "sort_desc", default = False, help = "sort torrents in descending order" )
	parser.add_option( "-a", "--add-file", action = "store_const", dest = "action", const = "add_file", help = "add torrents specified by local file names" )
	parser.add_option( "-u", "--add-url", action = "store_const", dest = "action", const = "add_url", help = "add torrents specified by urls" )
	parser.add_option( "--dir", dest = "download_dir", help = "directory to download added torrent, absolute or relative to current download dir (only for --add)" )
	parser.add_option( "--settings", action = "store_const", dest = "action", const = "settings_get", help = "show current server settings, optionally you can use specific setting keys (name name ...)" )
	parser.add_option( "--set", action = "store_const", dest = "action", const = "settings_set", help = "assign settings value (key1=value1 key2=value2 ...)" )
	parser.add_option( "--start", action = "store_const", dest = "action", const = "torrent_start", help = "start torrents (hash hash ...)" )
	parser.add_option( "--stop", action = "store_const", dest = "action", const = "torrent_stop", help = "stop torrents (hash hash ...)" )
	parser.add_option( "--pause", action = "store_const", dest = "action", const = "torrent_pause", help = "pause torrents (hash hash ...)" )
	parser.add_option( "--resume", action = "store_const", dest = "action", const = "torrent_resume", help = "resume torrents (hash hash ...)" )
	parser.add_option( "--recheck", action = "store_const", dest = "action", const = "torrent_recheck", help = "recheck torrents, torrent must be stopped first (hash hash ...)" )
	parser.add_option( "--remove", action = "store_const", dest = "action", const = "torrent_remove", help = "remove torrents (hash hash ...)" )
	parser.add_option( "--all", action = "store_true", dest = "all", default = False, help = "applies action to all torrents (for start, stop, pause, resume and recheck)" )
	parser.add_option( "-F", "--force", action = "store_true", dest = "force", default = False, help = "forces current command (for start and remove)" )
	parser.add_option( "--data", action = "store_true", dest = "with_data", default = False, help = "when removing torrent also remove its data (for remove, also enabled by --force)" )
	parser.add_option( "--torrent", action = "store_true", dest = "with_torrent", default = False, help = "when removing torrent also remove its torrent file (for remove with uTorrent server, also enabled by --force)" )
	parser.add_option( "-i", "--info", action = "store_const", dest = "action", const = "torrent_info", help = "show info and file/trackers list for the specified torrents (hash hash ...)" )
	parser.add_option( "--dump", action = "store_const", dest = "action", const = "torrent_dump", help = "show full torrent info in key=value view (hash hash ...)" )
	parser.add_option( "--download", action = "store_const", dest = "action", const = "download_file", help = "downloads specified file (hash.file_index)" )
	parser.add_option( "--set-file-prio", action = "store_const", dest = "action", const = "set_file_priority", help = "sets specified file priority, if you omit file_index then priority will be set for all files (hash[.file_index]=prio hash[.file_index]=prio ...) prio=0..3" )
	parser.add_option( "--set-props", action = "store_const", dest = "action", const = "set_props", help = "change properties of torrent, e.g. label; use --dump to view them (hash.name=value hash.name=value ...)" )
	parser.add_option( "--magnet", action = "store_const", dest = "action", const = "get_magnet", help = "generate magnet link for the specified torrents (hash hash ...)" )
	opts, args = parser.parse_args()
	
	try:

		if opts.action != None:
			utorrent = uTorrentConnection( opts.host, opts.user, opts.password ).utorrent()

		if opts.action == "server_version":
			if opts.verbose:
				print( utorrent.version().verbose_str() )
			else:
				print( utorrent.version() )

		elif opts.action == "torrent_list":
			total_ul, total_dl, count, total_size = 0, 0, 0, 0
			if not opts.sort_field in utorrent.TorrentClass.get_sortable_attrs():
				opts.sort_field = "name"
			for h, t in sorted( utorrent.torrent_list().items(), key = lambda x: getattr( x[1], opts.sort_field ), reverse = opts.sort_desc ):
				if not opts.active or opts.active and ( t.ul_speed > 0 or t.dl_speed > 0 ): # handle --active
					if opts.label == None or opts.label == t.label: # handle --label
						count += 1
						total_size += t.size
						if opts.verbose:
							print( t.verbose_str() )
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
				hash = utorrent.torrent_add_file( i, opts.download_dir )
				print( level1 + "Info hash = {}".format( hash ) )

		elif opts.action == "add_url":
			for i in args:
				print( "Submitting {}...".format( i ) )
				utorrent.torrent_add_url( i, opts.download_dir )

		elif opts.action == "settings_get":
			for i in utorrent.settings_get().items():
				if len( args ) == 0 or i[0] in args:
					print( "{} = {}".format( *i ) )

		elif opts.action == "settings_set":
			utorrent.settings_set( { k : v for k, v in [ i.split( "=" ) for i in args] } )

		elif opts.action == "torrent_start":
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( "Starting all torrents..." )
			else:
				print( "Starting " + ", ".join( args ) + "..." )
			utorrent.torrent_start( args, opts.force )

		elif opts.action == "torrent_stop":
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( "Stopping all torrents..." )
			else:
				print( "Stopping " + ", ".join( args ) + "..." )
			utorrent.torrent_stop( args )

		elif opts.action == "torrent_resume":
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( "Resuming all torrents..." )
			else:
				print( "Resuming " + ", ".join( args ) + "..." )
			utorrent.torrent_resume( args )

		elif opts.action == "torrent_pause":
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( "Pausing all torrents..." )
			else:
				print( "Pausing " + ", ".join( args ) + "..." )
			utorrent.torrent_pause( args )

		elif opts.action == "torrent_recheck":
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( "Queuing recheck for all torrents..." )
			else:
				print( "Queuing recheck " + ", ".join( args ) + "..." )
			utorrent.torrent_recheck( args )

		elif opts.action == "torrent_remove":
			print( "Removing " + ", ".join( args ) + "..." )
			if utorrent.api_version == uTorrentLinuxServer.api_version:
				utorrent.torrent_remove( args, opts.with_data or opts.force, opts.with_torrent or opts.force )
			else:
				utorrent.torrent_remove( args, opts.with_data or opts.force )

		elif opts.action == "torrent_info":
			tors = utorrent.torrent_list()
			files = utorrent.file_list( args )
			infos = utorrent.torrent_info( args )
			for hsh, fls in files.items():
				if opts.verbose:
					print( tors[hsh].verbose_str() )
				else:
					print( tors[hsh] )
				if opts.verbose:
					print( level1 + infos[hsh].verbose_str() )
				else:
					print( level1 + str( infos[hsh] ) )
				print( level1 + "Files:" )
				for f in fls:
					if opts.verbose:
						print( level2 + f.verbose_str() )
					else:
						print( level2 + str( f ) )
				print( level1 + "Trackers:" )
				for tr in infos[hsh].trackers:
					print( level2 + tr )

		elif opts.action == "torrent_dump":
			tors = utorrent.torrent_list()
			infos = utorrent.torrent_info( args )
			for hsh, info in infos.items():
				if opts.verbose:
					print( tors[hsh].verbose_str() )
				else:
					print( tors[hsh] )
				print( level1 + "Read-only:" )
				for name, value in sorted( tors[hsh].dump().items() ):
					if name != "label":
						if hasattr( tors[hsh], name + "_h" ):
							value = "{} ({})".format( value, getattr( tors[hsh], name + "_h" ) )
						print( level2 + "{} = {}".format( name, value ) )
				print( level1 + "Changeable:" )
				for name, value in sorted( itertools.chain( info.dump().items(), ( ( "label", tors[hsh].label ), ) ) ):
					if name != "trackers":
						print( level2 + "{} = {}".format( name, value ) )

		elif opts.action == "download_file":
			if utorrent.api_version != uTorrentLinuxServer.api_version:
				raise uTorrentError( "Downloading files only supported for uTorrent Server" )
			parent_hash, index = uTorrent.parse_hash_prop( args[0] )
			if index == None:
				print( "Downloading whole torrent is not supported yet, please specify file index" )
				sys.exit( 2 )
			index = int( index )
			files = utorrent.file_list( parent_hash )
			if len( files ) == 0:
				print( "Specified torrent or file does not exist" )
				sys.exit( 1 )
			filename = utorrent.pathmodule.basename( files[parent_hash][index].name )
			print( "Downloading {}...".format( filename ) )
			file = open( filename, "wb" )
			bar_width = 50
			size_calc = False
			increm = 0
			start_time = datetime.datetime.now()
			def progress( loaded, total ):
				global bar_width, size_calc, increm, start_time
				if not size_calc:
					size_calc = True
					increm = round( total / bar_width )
				progr = loaded // increm
				delta = datetime.datetime.now() - start_time
				delta = delta.seconds + delta.microseconds / 1000000
				print( "[{}{}] {} {}/s eta: {}{}".format(
					"*" * progr, "_" * ( bar_width - progr ),
					uTorrent.human_size( total ),
					uTorrent.human_size( loaded / delta ),
					uTorrent.human_time_delta( ( total - loaded ) / ( loaded / delta ) ),
					" " * 25
					), sep = "", end = ""
				)
				print( "\b" * ( bar_width + 70 ), end = "" )
				sys.stdout.flush()
			utorrent.file_get( args[0], buffer = file, progress_cb = progress )
			print( "" )

		elif opts.action == "set_file_priority":
			utorrent.file_set_priority( { k : v for k, v in [ i.split( "=" ) for i in args ] } )

		elif opts.action == "set_props":
			props = []
			for a in args:
				hsh, value = a.split( "=", 1 )
				hsh, name = hsh.split( ".", 1 )
				props.append( { hsh : { name : value } } )
			utorrent.torrent_set_props( props )

		elif opts.action == "get_magnet":
			if opts.verbose:
				tors = utorrent.torrent_list()
			for hsh, lnk in utorrent.torrent_get_magnet( args ).items():
				if opts.verbose:
					print( tors[hsh] )
				else:
					print( hsh )
				print( level1 + lnk )

		else:
			parser.print_help()

	except uTorrentError as e:
		print( e )
		sys.exit( 1 )
