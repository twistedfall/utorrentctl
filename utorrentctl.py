#!/usr/bin/python3

"""
	This program is free software: you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
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
	utorrentctl - uTorrent cli remote control utility
"""

import urllib.request, urllib.error, json, re, posixpath, ntpath
from MultipartPostHandler import MultipartPostHandler
from urllib.parse import quote
from config import utorrentcfg

class uTorrentError( Exception ):
	pass


class TorrentStatus:
	
	started = False
	checking = False
	start_after_check = False
	checked = False
	error = False
	paused = False
	queued = False
	loaded = False
	
	def __init__( self, status ):
		self.started = status & 1
		self.checking = status & 2
		self.start_after_check = status & 4
		self.checked = status & 8
		self.error = status & 16
		self.paused = status & 32
		self.queued = status & 64
		self.loaded = status & 128
		
	def __str__( self ):
		out = []
		if self.started:
			out.append( 'started' )
		if self.checking:
			out.append( 'checking' )
		if self.start_after_check:
			out.append( 'start after check' )
		if self.checked:
			out.append( 'checked' )
		if self.error:
			out.append( 'error' )
			out.append( 'paused' )
		if self.queued:
			out.append( 'queued' )
		if self.loaded:
			out.append( 'loaded' )
		return ', '.join( out )


class Torrent:
	
	_utorrent = None
	
	hash = ''
	status = None
	name = ''
	size = 0
	progress = 0.
	downloaded = 0
	uploaded = 0
	ratio = 0.
	upspeed = 0
	downspeed = 0
	eta = 0
	label = ''
	peers_connected = 0
	peers_total = 0
	seeds_connected = 0
	seeds_total = 0
	availability = 0
	queue_order = 0
	download_remain = 0
	url = ''
	rss_url = ''
	status_message = ''

	def __init__( self, torrent, utorrent ):
		self._utorrent = utorrent
		self.hash, status, self.name, self.size, progress, self.downloaded, \
			self.uploaded, ratio, self.upspeed, self.downspeed, self.eta, self.label, \
			self.peers_connected, self.peers_total, self.seeds_connected, self.seeds_total, self.availability, \
			self.queue_order, self.download_remain = torrent
		self.progress = progress / 10.
		self.ratio = ratio / 1000.
		self.status = TorrentStatus( status )
	
	def __str__( self ):
		return '{} {}'.format( self.hash, self.name )
	
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

class Label:
	
	name = ''
	torrent_count = 0
	
	def __init__( self, label ):
		self.name, self.torrent_count = label

	def __str__( self ):
		return '{} ({})'.format( self.name, self.torrent_count )


class Priority:
	
	priority = 0
	
	def __init__( self, priority ):
		self.priority = priority

	def __str__( self ):
		if self.priority == 0:
			return 'don\'t download'
		elif self.priority == 1:
			return 'low priority'
		elif self.priority == 2:
			return 'normal priority'
		elif self.priority == 3:
			return 'high priority'


class File:
	
	_parent_hash = ''
	
	name = ''
	size = 0
	size_h = ''
	downloaded = 0
	downloaded_h = ''
	priority = 0
	progress = 0.
	
	def __init__( self, file, parent_hash ):
		self._parent_hash = parent_hash
		self.name, self.size, self.downloaded, priority = file
		self.priority = Priority( priority )
		self.progress = round( float( self.downloaded ) / self.size * 100, 1 )
		self.size_h = uTorrent.human_size( self.size )
		self.downloaded_h = uTorrent.human_size( self.downloaded )

	def __str__( self ):
		return '[{: <15}] {: >5}% ({: >9} / {: >9}) {}'.format( self.priority, self.progress, self.downloaded_h, self.size_h, self.name )


class uTorrent:
	
	_host = ''
	_login = ''
	_password = ''
	
	_url = ''
	_opurl = ''
	_opener = None
	
	_build_version = 0
	_token = ''
	
	_retry_max = 3
	_pathmodule = None
	
	def __init__( self, host, login, password ):
		self._pathmodule = ntpath
		self.connect( host, login, password )
		
	def _get_data( self, loc, data = None, retry = True ):
		last_e = None
		for i in range( self._retry_max if not retry else 1 ):
			try:
				h = self._opener.open( self._opurl + loc, data )
				out = h.read().decode( 'utf8' )
				h.close();
				return out
			except urllib.error.HTTPError as e:
				if e.code == 400: # uTorrent usually gives those on unknown method
					raise uTorrentError( 'Invalid request' )
				elif e.code == 110: # Connection timed out
					print( 'retry' )
					pass
				else:
					raise e
		raise last_e
	
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
				return "{:.2f}{}".format( size, s )
			if s != suffixes[ -1 ]:
				size /= 1024.
		return "{:.2f}{}".format( size, suffixes[ -1 ] )
	
	def _get_hashes( self, torrents ):
		if not isinstance( torrents, ( tuple, list ) ):
			torrents = ( torrents, )
		out = []
		for t in torrents:
			if isinstance( t, Torrent ):
				out.append( t.hash )
			elif isinstance( t, str ):
				out.append( t )
			else:
				raise uTorrentError( 'Hash designation only supported via Torrent class or string' )
		return { 'hash' : out }

	def _build_opener( self ):
		authh = urllib.request.HTTPBasicAuthHandler()
		authh.add_password( 'uTorrent', self._url, self._login, self._password )
		self._opener = urllib.request.build_opener( authh, MultipartPostHandler )
		
	def _fetch_token( self ):
		data = self._get_data( 'token.html' )
		match = re.search( "<div .*?id='token'.*?>(.+?)</div>", data )
		if match == None:
			raise uTorrentError( 'Can\'t fetch security token' )
		self._token = match.group( 1 )
		self._opurl = '{}?token={}&'.format( self._url, quote( self._token, '' ) )
	
	def _update_build( self, res ):
		self._build_version = res[ 'build' ]
	
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
	
	def _do_action( self, action, params = None, params_str = None, data = None, retry = True ):
		return json.loads( self._get_data( self._action( action, params, params_str ), data ) )
	
	def connect( self, host, login, password ):
		self._host = host
		self._login = login
		self._password = password
		self._url = self._opurl = 'http://{}/gui/'.format( self._host )
		self._build_opener()
		self._fetch_token()
		
	def build_version( self ):
		if self._build_version == 0:
			self.torrent_start( '' )
		return self._build_version
	
	def torrent_list( self, labels = None ):
		res = self._do_action( 'list' )
		self._update_build( res )
		out = [ Torrent( i, self ) for i in res[ 'torrents' ] ]
		if labels != None:
			labels.extend( [ Label( i ) for i in res[ 'label' ] ] )
#		if rss_feeds != None:
#			rss_feeds.extend( res[ 'rssfeeds' ] )
#		if rss_filters != None:
#			rss_filters.extend( res[ 'rssfilters' ] )
		return out
	
	def torrent_add_file( self, filename, download_dir = None ):
		if download_dir != None:
			prev_dir = self.settings_get()[ 'dir_active_download' ]
			if not self._pathmodule.isabs( download_dir ):
				download_dir = self._pathmodule.dirname( prev_dir ) + self._pathmodule.sep + download_dir
			self.settings_set( { 'dir_active_download' : download_dir } )
		res = self._do_action( action = 'add-file', data = { 'torrent_file' : open( filename, 'rb' ) } );
		if download_dir != None:
			self.settings_set( { 'dir_active_download' : prev_dir } )
		if 'error' in res:
			raise uTorrentError( res[ 'error' ] )
		
	def torrent_start( self, torrents, force = False ):
		if force:
			res = self._do_action( 'forcestart', self._get_hashes( torrents ) )
		else:
			res = self._do_action( 'start', self._get_hashes( torrents ) )
		self._update_build( res )
		
	def torrent_forcestart( self, torrents ):
		return self.torrent_start( torrents, True )

	def torrent_stop( self, torrents ):
		res = self._do_action( 'stop', self._get_hashes( torrents ) )
		self._update_build( res )

	def torrent_pause( self, torrents ):
		res = self._do_action( 'pause', self._get_hashes( torrents ) )
		self._update_build( res )

	def torrent_resume( self, torrents ):
		res = self._do_action( 'unpause', self._get_hashes( torrents ) )
		self._update_build( res )

	def torrent_recheck( self, torrents ):
		res = self._do_action( 'recheck', self._get_hashes( torrents ) )
		self._update_build( res )

	def torrent_remove( self, torrents, with_data = False ):
		if with_data:
			res = self._do_action( 'removedata', self._get_hashes( torrents ) )
		else:
			res = self._do_action( 'remove', self._get_hashes( torrents ) )
		self._update_build( res )
		
	def torrent_remove_with_data( self, torrents ):
		return self.torrent_remove( torrents, True )

	def file_list( self, torrents ):
		res = self._do_action( 'getfiles', self._get_hashes( torrents ) )
		self._update_build( res )
		out = {}
		fi = iter( res[ 'files' ] );
		for hash in fi:
			out[ hash ] = [ File( f, hash ) for f in next( fi ) ]
		return out
	
	def settings_get( self ):
		res = self._do_action( 'getsettings' )
		self._update_build( res )
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
		res = self._do_action( action = 'setsetting', params_str = '&'.join( args ) )

		
class uTorrentServer( uTorrent ):
	
	def get_server_version( self ):
		res = self._do_action( 'getversion' )
		print( res )
		
def ut_connect( host, login, password ):
	return uTorrent( host, login, password )

if __name__ == '__main__':
	
	import optparse, sys
	
	def print_term( obj ):
		print( str( obj ).encode( sys.stdout.encoding, 'replace' ).decode( sys.stdout.encoding ) )
	
	parser = optparse.OptionParser()
	parser.add_option( '-H', '--host', dest = 'host', default = utorrentcfg[ 'host' ], help = 'host of uTorrent (hostname:port)' )
	parser.add_option( '-u', '--user', dest = 'user', default = utorrentcfg[ 'login' ], help = 'user name' )
	parser.add_option( '-p', '--password', dest = 'password', default = utorrentcfg[ 'password' ], help = 'user password' )
	parser.add_option( '-l', '--list-torrents', action = 'store_const', dest = 'action', const = 'torrent_list', help = 'list all torrents' )
	parser.add_option( '-f', '--list-files', action = 'store_const', dest = 'action', const = 'file_list', help = 'displays file list in torrent (hash hash ...)' )
	parser.add_option( '-a', '--add', action = 'store_const', dest = 'action', const = 'add', help = 'add torrents specified by local file names' )
	parser.add_option( '--dir', dest = 'dir', help = 'directory to download added torrent, if path is relative then it is made relative to current download path parent directory (only for --add)' )
	parser.add_option( '--settings', action = 'store_const', dest = 'action', const = 'settings_get', help = 'show current server settings, optionally you can use specific setting keys (name name ...)' )
	parser.add_option( '-s', '--set', action = 'store_const', dest = 'action', const = 'settings_set', help = 'assign settings value (key1=value1 key2=value2 ...)' )
	parser.add_option( '--start', action = 'store_const', dest = 'action', const = 'torrent_start', help = 'start torrents (hash hash ...)' )
	parser.add_option( '--stop', action = 'store_const', dest = 'action', const = 'torrent_stop', help = 'stop torrents (hash hash ...)' )
	parser.add_option( '--pause', action = 'store_const', dest = 'action', const = 'torrent_pause', help = 'pause torrents (hash hash ...)' )
	parser.add_option( '--resume', action = 'store_const', dest = 'action', const = 'torrent_resume', help = 'resume torrents (hash hash ...)' )
	parser.add_option( '--recheck', action = 'store_const', dest = 'action', const = 'torrent_recheck', help = 'recheck torrents, torrent must be stopped first (hash hash ...)' )
	parser.add_option( '--remove', action = 'store_const', dest = 'action', const = 'torrent_remove', help = 'remove torrents (hash hash ...)' )
	parser.add_option( '--force', action = 'store_true', dest = 'force', help = 'forces current command (only for --start)' )
	parser.add_option( '--with-data', action = 'store_true', dest = 'with_data', help = 'when removing torrent also remove its data (only for --remove)' )
	opts, args = parser.parse_args()
	
	if opts.action != None:
		try:
			utorrent = ut_connect( opts.host, opts.user, opts.password )
		except urllib.error.URLError as e:
			print_term( e )
			sys.exit( 2 )

	if opts.action == 'torrent_list':
		for i in utorrent.torrent_list():
			print_term( i )

	elif opts.action == 'file_list':
		for i in args:
			for h, fs in utorrent.file_list( i ).items():
				print_term( 'Torrent: ' + h )
				for f in fs:
					print_term( '+ ' + str( f ) )

	elif opts.action == 'add':
		for i in args:
			print( 'Submitting {}...'.format( i ) )
			try:
				utorrent.torrent_add_file( i, opts.dir )
			except uTorrentError as e:
				print_term( e )
				sys.exit( 1 )

	elif opts.action == 'settings_get':
		for i in utorrent.settings_get().items():
			if len( args ) == 0 or i[ 0 ] in args:
				print_term( '{} = {}'.format( *i ) )

	elif opts.action == 'settings_set':
		settings = {}
		for i in args:
			k, v = i.split( '=' )
			settings[ k ] = v
		utorrent.settings_set( settings )
		
	elif opts.action == 'torrent_start':
		for i in args:
			print( 'Starting {}...'.format( i ) )
			utorrent.torrent_start( i, opts.force )

	elif opts.action == 'torrent_stop':
		for i in args:
			print( 'Stopping {}...'.format( i ) )
			utorrent.torrent_stop( i )

	elif opts.action == 'torrent_resume':
		for i in args:
			print( 'Resuming {}...'.format( i ) )
			utorrent.torrent_resume( i )

	elif opts.action == 'torrent_pause':
		for i in args:
			print( 'Pausing {}...'.format( i ) )
			utorrent.torrent_pause( i )

	elif opts.action == 'torrent_recheck':
		for i in args:
			print( 'Queuing recheck {}...'.format( i ) )
			utorrent.torrent_recheck( i )

	elif opts.action == 'torrent_remove':
		for i in args:
			print( 'Removing {}...'.format( i ) )
			utorrent.torrent_remove( i, opts.with_data )

	else:
		parser.print_help()
