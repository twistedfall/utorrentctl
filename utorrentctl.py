#!/usr/bin/python3

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

import urllib.request, http.client, http.cookiejar, socket
import re, json, base64, posixpath, ntpath, email.generator, os.path, datetime, errno
from urllib.parse import quote
try:
	from config import utorrentcfg
except ImportError:
	utorrentcfg = { 'host' : None, 'login' : None, 'password' : None  }


class uTorrentError( Exception ):
	pass


class Version:

	product = ''
	major = 0
	minor = 0
	build = 0
	engine = 0
	ui = 0
	date = None
	user_agent = ''
	peer_id = ''
	device_id = ''

	def __init__( self, res ):
		if 'version' in res: # server returns full data
			self.product = res[ 'version' ][ 'product_code' ]
			self.major = res[ 'version' ][ 'major_version' ]
			self.minor = res[ 'version' ][ 'minor_version' ]
			self.build = res[ 'build' ]
			self.engine = res[ 'version' ][ 'engine_version' ]
			self.ui = res[ 'version' ][ 'ui_version' ]
			date = res[ 'version' ][ 'version_date' ].split( ' ' )
			self.date = datetime.datetime( *map( int, date[ 0 ].split( '-' ) + date[ 1 ].split( ':' ) ) )
			self.user_agent = res[ 'version' ][ 'user_agent' ]
			self.peer_id = res[ 'version' ][ 'peer_id' ]
			self.device_id = res[ 'version' ][ 'device_id' ]
		else:
			# fill some partially made up values as desktop client doesn't provide full info, only build
			self.product = 'desktop'
			self.major = 2
			self.minor = 4
			self.build = self.engine = self.ui = res[ 'build' ]
			self.user_agent = 'BTWebClient/2040({})'.format( self.build )
			self.peer_id = 'UT2040'

	def __str__( self ):
		return self.user_agent

	def verbose_str( self ):
		return '{} {}/{} {} v{}.0.{}.{}, engine v{}, ui v{}'.format(
			self.user_agent, self.device_id, self.peer_id, self.product,
			self.major, self.minor, self.build, self.engine, self.ui
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
			return 'Not loaded'
		if self.error:
			return 'Error'
		if self.checking:
			return 'Checked {:.1f}%'.format( self._progress )
		if self.paused:
			if self.queued:
				return 'Paused'
			else:
				return '[F] Paused'
		if self._progress == 100:
			if self.queued:
				if self.started:
					return 'Seeding'
				else:
					return 'Queued Seed'
			else:
				if self.started:
					return '[F] Seeding'
				else:
					return 'Finished'
		else: # self._progress < 100
			if self.queued:
				if self.started:
					return 'Downloading'
				else:
					return 'Queued'
			else:
				if self.started:
					return '[F] Downloading'
#				else:
#					return 'Stopped'
		return 'Stopped'

	def __lt__( self, other ):
		return self._value < other._value


class Torrent:

	_utorrent = None

	hash = ''
	status = None
	name = ''
	size = 0
	size_h = ''
	progress = 0. # in percent
	downloaded = 0
	downloaded_h = ''
	uploaded = 0
	uploaded_h = ''
	ratio = 0.
	ul_speed = 0
	ul_speed_h = ''
	dl_speed = 0
	dl_speed_h = ''
	eta = 0
	eta_h = ''
	label = ''
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
		return '{} {}'.format( self.hash, self.name )

	def verbose_str( self ):
		return '{} {: <15}{} {: >5.1f}% {: >9} D:{: >12} U:{: >12} {: <8} eta: {: <7} {}'.format(
			self.hash, self.status, ' ({})'.format( self.label ) if self.label else '', self.progress, self.size_h,
			self.dl_speed_h + '/s' if self.dl_speed > 0 else '', self.ul_speed_h + '/s' if self.ul_speed > 0 else '',
			self.ratio, self.eta_h, self.name
		)

	def fill( self, torrent ):
		self.hash, status, self.name, self.size, progress, self.downloaded, \
			self.uploaded, ratio, self.ul_speed, self.dl_speed, self.eta, self.label, \
			self.peers_connected, self.peers_total, self.seeds_connected, self.seeds_total, \
			self.availability, self.queue_order, self.dl_remain = torrent
		self.progress = progress / 10.
		self.ratio = ratio / 1000.
		self.status = TorrentStatus( status, self.progress )
		self.size_h = uTorrent.human_size( self.size )
		self.uploaded_h = uTorrent.human_size( self.uploaded )
		self.downloaded_h = uTorrent.human_size( self.downloaded )
		self.ul_speed_h = uTorrent.human_size( self.ul_speed )
		self.dl_speed_h = uTorrent.human_size( self.dl_speed )
		self.eta_h = uTorrent.human_time_delta( self.eta )

	@classmethod
	def get_sortable_attrs( cls ):
		return [ i for i in dir( cls ) if not re.search( '(?:^_|_h$)', i ) and not hasattr( getattr( cls, i ), '__call__' ) ]

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


class Torrent_Server( Torrent ):

	url = ''
	rss_url = ''
	status_message = ''

	def fill( self, torrent ):
		Torrent.fill( self, torrent[ 0 : 19 ] )
		self.url, self.rss_url, self.status_message, junk = torrent[ 19 : ]
	
	def remove( self, with_data = False, with_torrent = False ):
		return self._utorrent.torrent_remove( self, with_data, with_torrent )


class Label:

	name = ''
	torrent_count = 0

	def __init__( self, label ):
		self.name, self.torrent_count = label

	def __str__( self ):
		return '{} ({})'.format( self.name, self.torrent_count )


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
			return 'don\'t download'
		elif self.value == 1:
			return 'low priority'
		elif self.value == 2:
			return 'normal priority'
		elif self.value == 3:
			return 'high priority'
		else:
			return 'unknown priority'


class File:

	_utorrent = None

	_parent_hash = ''

	index = 0
	hash = ''
	name = ''
	size = 0
	size_h = ''
	downloaded = 0
	downloaded_h = ''
	priority = None
	progress = 0.

	def __init__( self, utorrent, parent_hash, index, file = None ):
		self._utorrent = utorrent
		self._parent_hash = parent_hash
		self.index = index
		self.hash = "{}.{}".format( self._parent_hash, self.index )
		if file:
			self.fill( file )

	def __str__( self ):
		return '{} {}'.format( self.hash, self.name )

	def verbose_str( self ):
		return '{: <44} [{: <15}] {: >5}% ({: >9} / {: >9}) {}'.format( self.hash, self.priority, self.progress, self.downloaded_h, self.size_h, self.name )

	def fill( self, file ):
		self.name, self.size, self.downloaded, priority = file
		self.priority = Priority( priority )
		self.progress = round( float( self.downloaded ) / self.size * 100, 1 )
		self.size_h = uTorrent.human_size( self.size )
		self.downloaded_h = uTorrent.human_size( self.downloaded )

	def set_priority( self, priority ):
		self._utorrent.file_set_priority( { self.hash : priority } )


class JobInfo:

	_utorrent = None

	hash = ''
	trackers = []
	ul_limit = 0
	dl_limit = 0
	superseed = 0
	dht = 0
	pex = 0
	seed_override = 0
	seed_ratio = 0
	seed_time = 0
	ul_slots = 0

	def __init__( self, utorrent, hash = None, jobinfo = None ):
		self._utorrent = utorrent
		self.hash = hash
		if jobinfo:
			self.fill( jobinfo )

	def fill( self, jobinfo ):
		self.hash = jobinfo[ 'hash' ]
		self.trackers = jobinfo[ 'trackers' ].strip().split( '\r\n\r\n' )
		self.ul_limit = jobinfo[ 'ulrate' ]
		self.dl_limit = jobinfo[ 'dlrate' ]
		self.superseed = jobinfo[ 'superseed' ]
		self.dht = jobinfo[ 'dht' ]
		self.pex = jobinfo[ 'pex' ]
		self.seed_override = jobinfo[ 'seed_override' ]
		self.seed_ratio = jobinfo[ 'seed_ratio' ]
		self.seed_time = jobinfo[ 'seed_time' ]
		self.ul_slots = jobinfo[ 'ulslots' ]

	def _tribool_status_str( self, status ):
		return 'not allowed' if status == -1 else ( 'disabled' if status == 0 else 'enabled' )

	def __str__( self ):
		return 'Limits D:{} U:{}'.format( self.dl_limit, self.ul_limit )

	def verbose_str( self ):
		return 'Limits D:{} U:{};  Superseed:{};  DHT:{};  PEX:{};  Queuing override:{}  Seed ratio:{};  Seed time:{};  Upload slots:{}'.format(
			self.dl_limit, self.ul_limit, self._tribool_status_str( self.superseed ), self._tribool_status_str( self.dht ),
			self._tribool_status_str( self.pex ), self._tribool_status_str( self.seed_override ), self.seed_ratio,
			uTorrent.human_time_delta( self.seed_time ), self.ul_slots
		)


class uTorrentConnection( http.client.HTTPConnection ):

	_host = ''
	_login = ''
	_password = ''

	_request = None
	_cookies = http.cookiejar.CookieJar()
	_token = ''

	_retry_max = 3

	_utorrent = None

	def __init__( self, host, login, password ):
		self._host = host
		self._login = login
		self._password = password
		self._url = 'http://{}/gui/'.format( self._host )
		self._request = urllib.request.Request( self._url )
		self._request.add_header( 'Authorization', 'Basic ' + base64.b64encode( '{}:{}'.format( self._login, self._password ).encode( 'latin1' ) ).decode( 'ascii' ) )
		http.client.HTTPConnection.__init__( self, self._request.host, timeout = 10 )
		self._fetch_token()

	def _get_data( self, loc, data = None, retry = True ):
		last_e = None
		for i in range( self._retry_max if retry else 1 ):
			try:
				headers = { k : v for k, v in self._request.header_items() }
				if data:
					bnd = email.generator._make_boundary()
					headers[ 'Content-Type' ] = 'multipart/form-data; boundary={}'.format( bnd )
					data = data.replace( '{{BOUNDARY}}', bnd )
				self._request.add_data( data )
				self.request( self._request.get_method(), self._request.selector + loc, self._request.get_data(), headers )
				resp = self.getresponse()
				out = resp.read().decode( 'utf8' )
				if resp.status == 400:
					last_e = uTorrentError( out )
					# if uTorrent server alpha is bound to the same port as WebUI then it will respond with 'invalid request' to the first request in the connection
					if not self._utorrent or type( self._utorrent ) == uTorrentServer:
						continue
					raise last_e
				elif resp.status == 404:
					raise uTorrentError( 'Invalid request' )
				elif resp.status == 401:
					raise uTorrentError( 'Autorization failed' )
				elif resp.status != 200:
					raise uTorrentError( '{}: {}'.format( resp.reason, resp.status ) )
				self._cookies.extract_cookies( resp, self._request )
				if len( self._cookies ) > 0:
					self._request.add_header( 'Cookie', '; '.join( [ '{}={}'.format( quote( c.name, '' ), quote( c.value, '' ) ) for c in self._cookies ] ) )
				return out
			except socket.gaierror as e:
				raise uTorrentError( e.args[ 1 ] )
			except socket.error as e:
				e = e.args[ 0 ]
				if str( e ) == 'timed out':
					last_e = uTorrentError( 'Timeout' )
					continue
				elif e.args[ 0 ] == errno.ECONNREFUSED:
					self.close()
					raise uTorrentError( e.args[ 1 ] )
			except http.client.CannotSendRequest as e:
				last_e = uTorrentError( 'Cannot send request' )
				self.close()
		if last_e:
			self.close()
			raise last_e

	def _fetch_token( self ):
		data = self._get_data( 'token.html' )
		match = re.search( "<div .*?id='token'.*?>(.+?)</div>", data )
		if match == None:
			raise uTorrentError( 'Can\'t fetch security token' )
		self._token = match.group( 1 )
		self._request = urllib.request.Request( '{}?token={}&'.format( self._request.get_full_url(), quote( self._token, '' ) ), headers = self._request.headers )

	def _action( self, action, params = None, params_str = None ):
		args = ''
		if params != None:
			for k, v in params.items():
				if isinstance( v, ( tuple, list ) ):
					for i in v:
						args += '&{}={}'.format( quote( k, '' ), quote( i, '' ) )
				else:
					args += '&{}={}'.format( quote( k, '' ), quote( v, '' ) )
		if params_str != None and params_str != '':
			args += '&' + params_str
		if action == 'list':
			return 'list=1' + args
		else:
			return 'action=' + quote( action, '' ) + args

	def do_action( self, action, params = None, params_str = None, data = None, retry = True ):
		# uTorrent can send incorrect overlapping array objects, this will fix them, converting them into list
		def obj_hook( obj ):
			out = {}
			for k, v in obj:
				if k in out:
					out[ k ].extend( v )
				else:
					out[ k ] = v
			return out
		return json.loads( self._get_data( self._action( action, params, params_str ), data, retry ), object_pairs_hook = obj_hook )

	def utorrent( self ):
		try:
			ver = Version( self.do_action( 'getversion' ) )
		except uTorrentError:
			self.close() # need to close connection as desktop utorrent doesn't want to communicate over this connection any further
			return uTorrent( self )
		if ver.product == 'server':
			return uTorrentServer( self, ver )
		else:
			raise uTorrentError( 'Unsupported server' )


class uTorrent:

	_url = ''

	_connection = None
	_version = None

	_TorrentClass = Torrent

	_pathmodule = ntpath

	api_version = 1 # http://forum.utorrent.com/viewtopic.php?id=25661

	@property
	def TorrentClass( self ):
		return self._TorrentClass


	def __init__( self, connection, version = None ):
		self._connection = connection
		self._connection._utorrent = self
		self._version = version

	@staticmethod
	def _setting_val( type, value ):
		if type == 0: # int
			return int( value )
		elif type == 1: # bool
			return value == 'true'
		else:
			return value

	@staticmethod
	def human_size( size, suffixes = ( 'B', 'kiB', 'MiB', 'GiB', 'TiB' ) ):
		for s in suffixes:
			if size < 1024:
				return "{:.2f}{}".format( round( size, 2 ), s )
			if s != suffixes[ -1 ]:
				size /= 1024.
		return "{:.2f}{}".format( round( size, 2 ), suffixes[ -1 ] )

	@staticmethod
	def human_time_delta( seconds, max_elems = 2 ):
		if seconds == -1:
			return 'inf'
		out = []
		reducer = ( ( 60 * 60 * 24 * 7, 'w' ), ( 60 * 60 * 24, 'd' ), ( 60 * 60, 'h' ), ( 60, 'm' ), ( 1, 's' ) )
		for d, c in reducer:
			v = int( seconds / d )
			seconds -= d * v
			if v or len( out ) > 0:
				out.append( '{}{}'.format( v, c ) )
			if len( out ) == max_elems:
				break
		if len( out ) == 0:
			out.append( '0{}'.format( reducer[ -1][ 1 ] ) )
		return ' '.join( out )

	def _create_torrent_upload( self, torrent_data, torrent_filename ):
		out = '\r\n'.join( (
			'--{{BOUNDARY}}',
			'Content-Disposition: form-data; name="torrent_file"; filename="{}"'.format( quote( torrent_filename, '' ) ),
			'Content-Type: application/x-bittorrent',
			'',
			torrent_data.decode( 'latin1' ),
			'--{{BOUNDARY}}',
			'',
		) )
		return out

	def _get_hashes( self, torrents ):
		if not hasattr( torrents, '__iter__' ) or isinstance( torrents, str ):
			torrents = ( torrents, )
		out = []
		for t in torrents:
			if isinstance( t, self._TorrentClass ):
				out.append( t.hash )
			elif isinstance( t, str ):
				out.append( t )
			else:
				raise uTorrentError( 'Hash designation only supported via Torrent class or string' )
		return out

	def _handle_download_dir( self, download_dir ):
		out = None
		if download_dir:
			out = self.settings_get()[ 'dir_active_download' ]
			if not self._pathmodule.isabs( download_dir ):
				download_dir = self._pathmodule.dirname( out ) + self._pathmodule.sep + download_dir
			self.settings_set( { 'dir_active_download' : download_dir } )
		return out

	def _handle_prev_dir( self, prev_dir ):
		if prev_dir:
			self.settings_set( { 'dir_active_download' : prev_dir } )

	def do_action( self, action, params = None, params_str = None, data = None, retry = True ):
		return self._connection.do_action( action, params, params_str, data, retry )

	def version( self ):
		if not self._version:
			self._version = Version( self.do_action( 'start' ) )
		return self._version

	def torrent_list( self, labels = None ):
		res = self.do_action( 'list' )
		out = { hash : torrent for hash, torrent in [ ( i[ 0 ], self._TorrentClass( self, i ) ) for i in res[ 'torrents' ] ] }
		if labels != None:
			labels.extend( [ Label( i ) for i in res[ 'label' ] ] )
#		if rss_feeds != None:
#			rss_feeds.extend( res[ 'rssfeeds' ] )
#		if rss_filters != None:
#			rss_filters.extend( res[ 'rssfilters' ] )
		return out

	def torrent_info( self, torrents ):
		res = self.do_action( 'getprops', { 'hash' : self._get_hashes( torrents ) } )
		return { hash : info for hash, info in [ ( i[ 'hash' ], JobInfo( self, jobinfo = i ) ) for i in res[ 'props' ] ] }

	def torrent_add_url( self, url, download_dir = None ):
		prev_dir = self._handle_download_dir( download_dir )
		res = self.do_action( 'add-url', { 's' : url } );
		self._handle_prev_dir( prev_dir )
		if 'error' in res:
			raise uTorrentError( res[ 'error' ] )

	def torrent_add_data( self, torrent_data, download_dir = None, filename = 'default.torrent' ):
		prev_dir = self._handle_download_dir( download_dir )
		res = self.do_action( 'add-file', data = self._create_torrent_upload( torrent_data, filename ) );
		self._handle_prev_dir( prev_dir )
		if 'error' in res:
			raise uTorrentError( res[ 'error' ] )

	def torrent_add_file( self, filename, download_dir = None ):
		f = open( filename, 'rb' )
		torrent_data = f.read()
		f.close()
		self.torrent_add_data( torrent_data, download_dir, os.path.basename( filename ) )

	def torrent_start( self, torrents, force = False ):
		if force:
			self.do_action( 'forcestart', { 'hash' : self._get_hashes( torrents ) } )
		else:
			self.do_action( 'start', { 'hash' : self._get_hashes( torrents ) } )

	def torrent_forcestart( self, torrents ):
		return self.torrent_start( torrents, True )

	def torrent_stop( self, torrents ):
		self.do_action( 'stop', { 'hash' : self._get_hashes( torrents ) } )

	def torrent_pause( self, torrents ):
		self.do_action( 'pause', { 'hash' : self._get_hashes( torrents ) } )

	def torrent_resume( self, torrents ):
		self.do_action( 'unpause', { 'hash' : self._get_hashes( torrents ) } )

	def torrent_recheck( self, torrents ):
		self.do_action( 'recheck', { 'hash' : self._get_hashes( torrents ) } )

	def torrent_remove( self, torrents, with_data = False ):
		if with_data:
			self.do_action( 'removedata', { 'hash' : self._get_hashes( torrents ) } )
		else:
			self.do_action( 'remove', { 'hash' : self._get_hashes( torrents ) } )

	def torrent_remove_with_data( self, torrents ):
		return self.torrent_remove( torrents, True )

	def file_list( self, torrents ):
		res = self.do_action( 'getfiles', { 'hash' : self._get_hashes( torrents ) } )
		out = {}
		if 'files' in res:
			fi = iter( res[ 'files' ] );
			for hash in fi:
				out[ hash ] = [ File( self, hash, i, f ) for i, f in enumerate( next( fi ) ) ]
		return out

	def file_set_priority( self, files ):
		args = []
		for hash, prio in files.items():
			if isinstance( hash, File ):
				hash = hash.hash
			if not isinstance( prio, Priority ):
				prio = Priority( prio )
			parent_hash, index = hash.split( '.', 1 )
			args.append( 'hash={}&p={}&f={}'.format( quote( parent_hash, '' ), quote( str( prio.value ), '' ), quote( index, '' ) ) )
			self.do_action( 'setprio', params_str = '&'.join( args ) )

	def settings_get( self ):
		res = self.do_action( 'getsettings' )
		out = {}
		for name, type, value in res[ 'settings' ]:
			out[ name ] = self._setting_val( type, value )
		return out

	def settings_set( self, settings ):
		args = []
		for k, v in settings.items():
			if isinstance( v, bool ):
				v = int( v )
			args.append( 's={}&v={}'.format( quote( k, '' ), quote( str( v ), '' ) ) )
		self.do_action( 'setsetting', params_str = '&'.join( args ) )


class uTorrentServer( uTorrent ):

	_TorrentClass = Torrent_Server

	_pathmodule = posixpath

	api_version = 2 # http://download.utorrent.com/linux/utorrent-server-3.0-21886.tar.gz:bittorrent-server-v3_0/docs/uTorrent_Server.html

	def settings_get( self, extended_attributes = False ):
		res = self.do_action( 'getsettings' )
		out = {}
		for name, type, value, attrs in res[ 'settings' ]:
			out[ name ] = self._setting_val( type, value )
		return out

	def version( self ):
		if not self._version:
			self._version = Version( self.do_action( 'getversion' ) )
		return self._version

	def torrent_remove( self, torrents, with_data = False, with_torrent = False ):
		if with_data:
			if with_torrent:
				self.do_action( 'removedatatorrent', { 'hash' : self._get_hashes( torrents ) } )
			else:
				self.do_action( 'removedata', { 'hash' : self._get_hashes( torrents ) } )
		else:
			if with_torrent:
				self.do_action( 'removetorrent', { 'hash' : self._get_hashes( torrents ) } )
			else:
				self.do_action( 'remove', { 'hash' : self._get_hashes( torrents ) } )

	def torrent_remove_with_torrent( self, torrents ):
		return self.torrent_remove( torrents, False, True )

	def torrent_remove_with_data_torrent( self, torrents ):
		return self.torrent_remove( torrents, True, True )

	def get_file( self, file ):
		if isinstance( file, File ):
			file = file.hash
		parent_hash, index = file.split( '.', 1 )
#		args.append( 'hash={}&p={}&f={}'.format( quote( parent_hash, ''), quote( str( prio.value ), '' ), quote( index, '' ) ) )
#		self.do_action( 'setprio', params_str = '&'.join( args ) )


if __name__ == '__main__':

	import optparse, sys

	print_orig = print

	def print( obj ):
		global print_orig
		print_orig( str( obj ).encode( sys.stdout.encoding, 'replace' ).decode( sys.stdout.encoding ) )

	level1 = '   '
	level2 = '      '

	parser = optparse.OptionParser()
	parser.add_option( '-H', '--host', dest = 'host', default = utorrentcfg[ 'host' ], help = 'host of uTorrent (hostname:port)' )
	parser.add_option( '-u', '--user', dest = 'user', default = utorrentcfg[ 'login' ], help = 'user name' )
	parser.add_option( '-p', '--password', dest = 'password', default = utorrentcfg[ 'password' ], help = 'user password' )
	parser.add_option( '--nv', '--no-verbose', action = 'store_false', dest = 'verbose', default = True, help = 'show shortened info in most cases (quicker, saves network traffic)' )
	parser.add_option( '--server-version', action = 'store_const', dest = 'action', const = 'server_version', help = 'print uTorrent server version' )
	parser.add_option( '-l', '--list-torrents', action = 'store_const', dest = 'action', const = 'torrent_list', help = 'list all torrents' )
	parser.add_option( '-c', '--active', action = 'store_true', dest = 'active', default = False, help = 'when listing torrents display only active ones (speed > 0)' )
	parser.add_option( '-s', '--sort', default = 'name', dest = 'sort_field', help = 'sort torrents, values are: availability, dl_remain, dl_speed, downloaded, eta, hash, label, name, peers_connected, peers_total, progress, queue_order, ratio, seeds_connected, seeds_total, size, status, ul_speed, uploaded + url, rss_url (for server)' )
	parser.add_option( '--desc', action = 'store_true', dest = 'sort_desc', default = False, help = 'sort torrents in descending order' )
	parser.add_option( '-a', '--add-file', action = 'store_const', dest = 'action', const = 'add_file', help = 'add torrents specified by local file names' )
	parser.add_option( '--add-url', action = 'store_const', dest = 'action', const = 'add_url', help = 'add torrents specified by urls' )
	parser.add_option( '--dir', dest = 'dir', help = 'directory to download added torrent, if path is relative then it is made relative to current download path parent directory (only for --add)' )
	parser.add_option( '-g', '--settings', action = 'store_const', dest = 'action', const = 'settings_get', help = 'show current server settings, optionally you can use specific setting keys (name name ...)' )
	parser.add_option( '-s', '--set', action = 'store_const', dest = 'action', const = 'settings_set', help = 'assign settings value (key1=value1 key2=value2 ...)' )
	parser.add_option( '--start', action = 'store_const', dest = 'action', const = 'torrent_start', help = 'start torrents (hash hash ...)' )
	parser.add_option( '--stop', action = 'store_const', dest = 'action', const = 'torrent_stop', help = 'stop torrents (hash hash ...)' )
	parser.add_option( '--pause', action = 'store_const', dest = 'action', const = 'torrent_pause', help = 'pause torrents (hash hash ...)' )
	parser.add_option( '--resume', action = 'store_const', dest = 'action', const = 'torrent_resume', help = 'resume torrents (hash hash ...)' )
	parser.add_option( '--recheck', action = 'store_const', dest = 'action', const = 'torrent_recheck', help = 'recheck torrents, torrent must be stopped first (hash hash ...)' )
	parser.add_option( '--remove', action = 'store_const', dest = 'action', const = 'torrent_remove', help = 'remove torrents (hash hash ...)' )
	parser.add_option( '--all', action = 'store_true', dest = 'all', default = False, help = 'applies action to all torrents (only for start, stop, pause, resume and recheck)' )
	parser.add_option( '--force', action = 'store_true', dest = 'force', default = False, help = 'forces current command (only for start)' )
	parser.add_option( '--data', action = 'store_true', dest = 'with_data', default = False, help = 'when removing torrent also remove its data (only for remove)' )
	parser.add_option( '--torrent', action = 'store_true', dest = 'with_torrent', default = False, help = 'when removing torrent also remove its torrent file (only for remove with uTorrent server)' )
	parser.add_option( '-i', '--info', action = 'store_const', dest = 'action', const = 'torrent_info', help = 'show settings and trackers for the specified torrents (hash hash ...)' )
	parser.add_option( '-f', '--list-files', action = 'store_const', dest = 'action', const = 'file_list', help = 'displays file list within torrents (hash hash ...)' )
	parser.add_option( '-I', '--full-info', action = 'store_const', dest = 'action', const = 'torrent_full_info', help = 'displays full information about torrents (hash hash ...)' )
	parser.add_option( '--set-file-priority', action = 'store_const', dest = 'action', const = 'set_file_priority', help = 'sets specified file priority (hash.file_index=prio hash.file_index=prio ...) prio=0..3' )
	opts, args = parser.parse_args()
	
	try:

		if opts.action != None:
			utorrent = uTorrentConnection( opts.host, opts.user, opts.password ).utorrent()

		if opts.action == 'server_version':
			if opts.verbose:
				print( utorrent.version().verbose_str() )
			else:
				print( utorrent.version() )

		elif opts.action == 'torrent_list':
			total_ul, total_dl = 0, 0
			if not opts.sort_field in utorrent.TorrentClass.get_sortable_attrs():
				opts.sort_field = 'name'
			for h, t in sorted( utorrent.torrent_list().items(), key = lambda x: getattr( x[ 1 ], opts.sort_field ), reverse = opts.sort_desc ):
				if opts.verbose:
					if not opts.active or opts.active and ( t.ul_speed > 0 or t.dl_speed > 0 ):
						print( t.verbose_str() )
					total_ul += t.ul_speed
					total_dl += t.dl_speed
				else:
					print( t )
			if opts.verbose:
				print( 'Total speed: D:{}/s U:{}/s'.format( uTorrent.human_size( total_dl ), uTorrent.human_size( total_ul ) ) )

		elif opts.action == 'add_file':
			for i in args:
				print( 'Submitting {}...'.format( i ) )
				utorrent.torrent_add_file( i, opts.dir )

		elif opts.action == 'add_url':
			for i in args:
				print( 'Submitting {}...'.format( i ) )
				utorrent.torrent_add_url( i, opts.dir )

		elif opts.action == 'settings_get':
			for i in utorrent.settings_get().items():
				if len( args ) == 0 or i[ 0 ] in args:
					print( '{} = {}'.format( *i ) )

		elif opts.action == 'settings_set':
			utorrent.settings_set( { k : v for k, v in [ i.split( '=' ) for i in args ] } )

		elif opts.action == 'torrent_start':
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( 'Starting all torrents...' )
			else:
				print( 'Starting ' + ', '.join( args ) + '...' )
			utorrent.torrent_start( args, opts.force )

		elif opts.action == 'torrent_stop':
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( 'Stopping all torrents...' )
			else:
				print( 'Stopping ' + ', '.join( args ) + '...' )
			utorrent.torrent_stop( args )

		elif opts.action == 'torrent_resume':
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( 'Resuming all torrents...' )
			else:
				print( 'Resuming ' + ', '.join( args ) + '...' )
			utorrent.torrent_resume( args )

		elif opts.action == 'torrent_pause':
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( 'Pausing all torrents...' )
			else:
				print( 'Pausing ' + ', '.join( args ) + '...' )
			utorrent.torrent_pause( args )

		elif opts.action == 'torrent_recheck':
			if opts.all:
				args = utorrent.torrent_list().keys()
				print( 'Queuing recheck for all torrents...' )
			else:
				print( 'Queuing recheck ' + ', '.join( args ) + '...' )
			utorrent.torrent_recheck( args )

		elif opts.action == 'torrent_remove':
			print( 'Removing ' + ', '.join( args ) + '...' )
			if utorrent.api_version == 1:
				utorrent.torrent_remove( args, opts.with_data )
			elif utorrent.api_version == 2:
				utorrent.torrent_remove( args, opts.with_data, opts.with_torrent )

		elif opts.action == 'torrent_info':
			if opts.verbose:
				tors = utorrent.torrent_list()
			for hsh, info in utorrent.torrent_info( args ).items():
				if opts.verbose:
					print( '{} ({})'.format( tors[ hsh ].name, hsh ) )
				else:
					print( 'Torrent: ' + hsh )
				if opts.verbose:
					print( level1 + info.verbose_str() )
				else:
					print( level1 + str( info ) )
				print( level1 + 'Trackers:' )
				for tr in info.trackers:
					print( level2 + tr )

		elif opts.action == 'file_list':
			if opts.verbose:
				tors = utorrent.torrent_list()
			for hsh, fs in utorrent.file_list( args ).items():
				if opts.verbose:
					print( '{} ({})'.format( tors[ hsh ].name, hsh ) )
				else:
					print( 'Torrent: ' + hsh )
				for f in fs:
					if opts.verbose:
						print( level1 + f.verbose_str() )
					else:
						print( level1 + str( f ) )

		elif opts.action == 'torrent_full_info':
			tors = utorrent.torrent_list()
			files = utorrent.file_list( args )
			infos = utorrent.torrent_info( args )
			for hsh, fls in files.items():
				if opts.verbose:
					print( tors[ hsh ].verbose_str() )
				else:
					print( tors[ hsh ] )
				if opts.verbose:
					print( level1 + infos[ hsh ].verbose_str() )
				else:
					print( level1 + str( infos[ hsh ] ) )
				print( level1 + 'Files:' )
				for f in fls:
					if opts.verbose:
						print( level2 + f.verbose_str() )
					else:
						print( level2 + str( f ) )
				print( level1 + 'Trackers:' )
				for tr in infos[ hsh ].trackers:
					print( level2 + tr )

		elif opts.action == 'set_file_priority':
			utorrent.file_set_priority( { k : v for k, v in [ i.split( '=' ) for i in args ] } )

		else:
			parser.print_help()

	except uTorrentError as e:
		print( e )
		sys.exit( 1 )
