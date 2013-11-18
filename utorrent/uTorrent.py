"""
uTorrent
"""

import datetime
import ntpath
import os
import re
from hashlib import sha1
from collections import OrderedDict
import posixpath
import utorrent.rss as rss
import utorrent
import utorrent.torrent
import utorrent.job_info
import utorrent.file
import utorrent.priority


class Desktop:
	"""
	Represents desktop version of uTorrent client with minimal set of features
	"""
	_url = ""
	""" :type: str """

	_connection = None
	""" :type: utorrent.connection.Connection """
	_version = None
	""" :type: utorrent.uTorrent.Version """

	_TorrentClass = utorrent.torrent.Torrent
	""" :type: utorrent.torrent.Torrent """
	_JobInfoClass = utorrent.job_info.JobInfo
	""" :type: utorrent.job_info.JobInfo """
	_FileClass = utorrent.file.File
	""" :type: utorrent.file.File """

	_pathmodule = ntpath

	_list_cache_id = 0
	_torrent_cache = None
	""" :type: dict """
	_rssfeed_cache = None
	""" :type: dict """
	_rssfilter_cache = None
	""" :type: dict """

	api_version = 1 # http://user.utorrent.com/community/developers/webapi

	@property
	def TorrentClass( self ):
		"""
		Returns class responsible for storing the torrent information.

		:rtype: utorrent.torrent.Torrent
		"""
		return self._TorrentClass

	@property
	def JobInfoClass( self ):
		"""
		Returns class responsible for storing the torrent information.

		:return: :rtype:
		"""
		return self._JobInfoClass

	@property
	def pathmodule( self ):
		"""
		Returns path module responsible for handling system specific paths.

		:return: :rtype:
		"""
		return self._pathmodule

	def __init__( self, connection, version = None ):
		"""
		:type connection: utorrent.connection.Connection
		:type version: utorrent.uTorrent.Version
		"""
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
	def is_hash( torrent_hash ):
		return re.match( "[0-9A-F]{40}$", torrent_hash, re.IGNORECASE )

	@staticmethod
	def get_info_hash( torrent_data ):
		return sha1( utorrent.bencode( utorrent.bdecode( torrent_data )["info"] ) ).hexdigest( ).upper( )

	@classmethod
	def check_hash( cls, torrent_hash ):
		if not cls.is_hash( torrent_hash ):
			raise utorrent.uTorrentError( "Incorrect hash: {}".format( torrent_hash ) )

	@classmethod
	def parse_hash_prop( cls, hash_prop ):
		if isinstance( hash_prop, ( utorrent.file.File, utorrent.torrent.Torrent, utorrent.job_info.JobInfo ) ):
			hash_prop = hash_prop.hash_code
		try:
			parent_hash, prop = hash_prop.split( ".", 1 )
		except ValueError:
			parent_hash, prop = hash_prop, None
		parent_hash = parent_hash.upper( )
		cls.check_hash( parent_hash )
		return parent_hash, prop

	def resolve_torrent_hashes( self, hashes, torrent_list = None ):
		out = []
		if torrent_list is None:
			torrent_list = self.torrent_list( )
		for h in hashes:
			if h in torrent_list:
				out.append( torrent_list[h].name )
		return out

	def resolve_feed_ids( self, ids, rss_list = None ):
		out = []
		if rss_list is None:
			rss_list = self.rss_list( )
		for feed_id in ids:
			if int( feed_id ) in rss_list:
				out.append( rss_list[int( feed_id )].url )
		return out

	def resolve_filter_ids( self, ids, filter_list = None ):
		out = []
		if filter_list is None:
			filter_list = self.rssfilter_list( )
		for filter_id in ids:
			if int( filter_id ) in filter_list:
				out.append( filter_list[int( filter_id )].name )
		return out

	def parse_file_list_structure( self, file_list ):
		out = OrderedDict( )
		for file in file_list:
			parts = file.name.split( self.pathmodule.sep )
			cur_out = out
			for i, part in enumerate( parts ):
				is_last = i == len( parts ) - 1
				if not part in cur_out:
					if not is_last:
						cur_out[part] = OrderedDict( )
				if is_last:
					cur_out[part] = file
				else:
					cur_out = cur_out[part]
		return out

	def _create_torrent_upload( self, torrent_data, torrent_filename ):
		out = "\r\n".join( (
		"--{{BOUNDARY}}", 'Content-Disposition: form-data; name="torrent_file"; filename="{}"'.format( utorrent._url_quote( torrent_filename ) ),
		"Content-Type: application/x-bittorrent", "", torrent_data.decode( "latin1" ), "--{{BOUNDARY}}", "",
		) )
		return out

	def _get_hashes( self, torrents ):
		if not utorrent.is_list_type( torrents ):
			torrents = ( torrents, )
		out = []
		for t in torrents:
			if isinstance( t, self._TorrentClass ):
				hsh = t.hash_code
			elif isinstance( t, str ):
				hsh = t
			else:
				raise utorrent.uTorrentError( "Hash designation only supported via Torrent class or string" )
			self.check_hash( hsh )
			out.append( hsh )
		return out

	def _handle_download_dir( self, download_dir ):
		out = None
		if download_dir:
			out = self.settings_get( )["dir_active_download"]
			if not self._pathmodule.isabs( download_dir ):
				download_dir = out + self._pathmodule.sep + download_dir
			self.settings_set( { "dir_active_download": download_dir } )
		return out

	def _handle_prev_dir( self, prev_dir ):
		if prev_dir:
			self.settings_set( { "dir_active_download": prev_dir } )

	def do_action( self, action, params = None, params_str = None, data = None, retry = True, range_start = None, range_len = None, save_buffer = None,
	               progress_cb = None ):
		return self._connection.do_action( action = action, params = params, params_str = params_str, data = data, retry = retry,
		                                   range_start = range_start, range_len = range_len, save_buffer = save_buffer, progress_cb = progress_cb )

	def version( self ):
		if not self._version:
			self._version = Version( self.do_action( "start" ) )
		return self._version

	def _fetch_torrent_list( self ):
		if self._list_cache_id:
			out = self.do_action( "list", { "cid": self._list_cache_id } )
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
				self._torrent_cache = { hsh: torrent for hsh, torrent in [( t[0], t ) for t in out["torrents"]] }
			if "rssfeeds" in out:
				self._rssfeed_cache = { feed_id: feed for feed_id, feed in [( r[0], r ) for r in out["rssfeeds"]] }
			if "rssfilters" in out:
				self._rssfilter_cache = { filter_id: filter_props for filter_id, filter_props in [( f[0], f ) for f in out["rssfilters"]] }
		self._list_cache_id = out["torrentc"]
		return out

	def torrent_list( self, labels = None, rss_feeds = None, rss_filters = None ):
		res = self._fetch_torrent_list( )
		out = { h: self._TorrentClass( self, t ) for h, t in self._torrent_cache.items( ) }
		if labels is not None:
			labels.extend( [utorrent.torrent.Label( i ) for i in res["label"]] )
		if rss_feeds is not None:
			for feed_id, feed in self._rssfeed_cache.items( ):
				rss_feeds[feed_id] = rss.Feed( feed )
		if rss_filters is not None:
			for filter_id, filter_props in self._rssfilter_cache.items( ):
				rss_filters[filter_id] = rss.Filter( filter_props )
		return out

	def torrent_info( self, torrents ):
		res = self.do_action( "getprops", { "hash": self._get_hashes( torrents ) } )
		if not "props" in res:
			return { }
		return { hsh: info for hsh, info in [( i["hash"], self._JobInfoClass( self, jobinfo = i ) ) for i in res["props"]] }

	def torrent_add_url( self, url, download_dir = None ):
		prev_dir = self._handle_download_dir( download_dir )
		res = self.do_action( "add-url", { "s": url } )
		self._handle_prev_dir( prev_dir )
		if "error" in res:
			raise utorrent.uTorrentError( res["error"] )
		if url[0:7] == "magnet:":
			m = re.search( "urn:btih:([0-9A-F]{40})", url, re.IGNORECASE )
			if m:
				return m.group( 1 ).upper( )
		return None

	def torrent_add_data( self, torrent_data, download_dir = None, filename = "default.torrent" ):
		prev_dir = self._handle_download_dir( download_dir )
		res = self.do_action( "add-file", data = self._create_torrent_upload( torrent_data, filename ) )
		self._handle_prev_dir( prev_dir )
		if "error" in res:
			raise utorrent.uTorrentError( res["error"] )
		return self.get_info_hash( torrent_data )

	def torrent_add_file( self, filename, download_dir = None ):
		f = open( filename, "rb" )
		torrent_data = f.read( )
		f.close( )
		return self.torrent_add_data( torrent_data, download_dir, os.path.basename( filename ) )

	def torrent_set_props( self, props ):
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
		args = []
		for arg in props:
			for hsh, t_prop in arg.items( ):
				for name, value in t_prop.items( ):
					args.append(
						"hash={}&s={}&v={}".format( utorrent._url_quote( hsh ), utorrent._url_quote( name ), utorrent._url_quote( str( value ) ) ) )
		self.do_action( "setprops", params_str = "&".join( args ) )

	def torrent_start( self, torrents, force = False ):
		if force:
			self.do_action( "forcestart", { "hash": self._get_hashes( torrents ) } )
		else:
			self.do_action( "start", { "hash": self._get_hashes( torrents ) } )

	def torrent_forcestart( self, torrents ):
		return self.torrent_start( torrents, True )

	def torrent_stop( self, torrents ):
		self.do_action( "stop", { "hash": self._get_hashes( torrents ) } )

	def torrent_pause( self, torrents ):
		self.do_action( "pause", { "hash": self._get_hashes( torrents ) } )

	def torrent_resume( self, torrents ):
		self.do_action( "unpause", { "hash": self._get_hashes( torrents ) } )

	def torrent_recheck( self, torrents ):
		self.do_action( "recheck", { "hash": self._get_hashes( torrents ) } )

	def torrent_remove( self, torrents, with_data = False ):
		if with_data:
			self.do_action( "removedata", { "hash": self._get_hashes( torrents ) } )
		else:
			self.do_action( "remove", { "hash": self._get_hashes( torrents ) } )

	def torrent_remove_with_data( self, torrents ):
		return self.torrent_remove( torrents, True )

	def torrent_get_magnet( self, torrents, self_tracker = False ):
		out = { }
		tors = self.torrent_list( )
		for t in torrents:
			t = t.upper( )
			self.check_hash( t )
			if t in tors:
				if self_tracker:
					trackers = [self._connection.request_obj.get_full_url( ) + "announce"]
				else:
					trackers = self.torrent_info( t )[t].trackers
				trackers = "&".join( [""] + ["tr=" + utorrent._url_quote( t ) for t in trackers] )
				out[t] = "magnet:?xt=urn:btih:{}&dn={}{}".format( utorrent._url_quote( t.lower( ) ), utorrent._url_quote( tors[t].name ), trackers )
		return out

	def file_list( self, torrents ):
		res = self.do_action( "getfiles", { "hash": self._get_hashes( torrents ) } )
		out = { }
		if "files" in res:
			fi = iter( res["files"] )
			for hsh in fi:
				out[hsh] = [self._FileClass( self, hsh, i, f ) for i, f in enumerate( next( fi ) )]
		return out

	def file_set_priority( self, files ):
		args = []
		filecount_cache = { }
		for hsh, prio in files.items( ):
			parent_hash, index = self.parse_hash_prop( hsh )
			if not isinstance( prio, utorrent.priority.Priority ):
				prio = utorrent.priority.Priority( prio )
			if index is None:
				if not parent_hash in filecount_cache:
					filecount_cache[parent_hash] = len( self.file_list( parent_hash )[parent_hash] )
				for i in range( filecount_cache[parent_hash] ):
					args.append( "hash={}&p={}&f={}".format( utorrent._url_quote( parent_hash ), utorrent._url_quote( str( prio.value ) ),
					                                         utorrent._url_quote( str( i ) ) ) )
			else:
				args.append( "hash={}&p={}&f={}".format( utorrent._url_quote( parent_hash ), utorrent._url_quote( str( prio.value ) ),
				                                         utorrent._url_quote( str( index ) ) ) )
		self.do_action( "setprio", params_str = "&".join( args ) )

	def settings_get( self ):
		res = self.do_action( "getsettings" )
		out = { }
		for name, valueType, value in res["settings"]:
			out[name] = self._setting_val( valueType, value )
		return out

	def settings_set( self, settings ):
		args = []
		for k, v in settings.items( ):
			if isinstance( v, bool ):
				v = int( v )
			args.append( "s={}&v={}".format( utorrent._url_quote( k ), utorrent._url_quote( str( v ) ) ) )
		self.do_action( "setsetting", params_str = "&".join( args ) )

	def rss_list( self ):
		rss_feeds = { }
		self.torrent_list( rss_feeds = rss_feeds )
		return rss_feeds

	def rssfilter_list( self ):
		rss_filters = { }
		self.torrent_list( rss_filters = rss_filters )
		return rss_filters


class Falcon( Desktop ):
	_TorrentClass = utorrent.torrent.Torrent_API2
	_JobInfoClass = utorrent.job_info.JobInfo
	_FileClass = utorrent.file.File_API2

	api_version = 1.9
	# no description yet, what I found out:
	# * no support for getversion

	def torrent_remove( self, torrents, with_data = False, with_torrent = False ):
		if with_data:
			if with_torrent:
				self.do_action( "removedatatorrent", { "hash": self._get_hashes( torrents ) } )
			else:
				self.do_action( "removedata", { "hash": self._get_hashes( torrents ) } )
		else:
			if with_torrent:
				self.do_action( "removetorrent", { "hash": self._get_hashes( torrents ) } )
			else:
				self.do_action( "remove", { "hash": self._get_hashes( torrents ) } )

	def torrent_remove_with_torrent( self, torrents ):
		return self.torrent_remove( torrents, False, True )

	def torrent_remove_with_data_torrent( self, torrents ):
		return self.torrent_remove( torrents, True, True )

	def file_get( self, file_hash, buffer, range_start = None, range_len = None, progress_cb = None ):
		parent_hash, index = self.parse_hash_prop( file_hash )
		self.do_action( "proxy", { "id": parent_hash, "file": index }, range_start = range_start, range_len = range_len, save_buffer = buffer,
		                progress_cb = progress_cb )

	def settings_get( self, extended_attributes = False ):
		res = self.do_action( "getsettings" )
		out = { }
		for name, valueType, value, attrs in res["settings"]:
			out[name] = self._setting_val( valueType, value )
		return out

	def rss_add( self, url ):
		return self.rss_update( -1, { "url": url } )

	def rss_update( self, feed_id, params ):
		params["feed-id"] = feed_id
		res = self.do_action( "rss-update", params )
		if "rss_ident" in res:
			return int( res["rss_ident"] )
		return feed_id

	def rss_remove( self, feed_id ):
		self.do_action( "rss-remove", { "feed-id": feed_id } )

	def rssfilter_add( self, feed_id = -1 ):
		return self.rssfilter_update( -1, { "feed-id": feed_id } )

	def rssfilter_update( self, filter_id, params ):
		params["filter-id"] = filter_id
		res = self.do_action( "filter-update", params )
		if "filter_ident" in res:
			return int( res["filter_ident"] )
		return filter_id

	def rssfilter_remove( self, filter_id ):
		self.do_action( "filter-remove", { "filter-id": filter_id } )

	def xfer_history_get( self ):
		return self.do_action( "getxferhist" )["transfer_history"]

	def xfer_history_reset( self ):
		self.do_action( "resetxferhist" )


class LinuxServer( Falcon ):
	_pathmodule = posixpath

	api_version = 2 # http://download.utorrent.com/linux/utorrent-server-3.0-21886.tar.gz:bittorrent-server-v3_0/docs/uTorrent_Server.html

	def version( self ):
		if not self._version:
			self._version = Version( self.do_action( "getversion" ) )
		return self._version


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
			raise utorrent.uTorrentError( "Cannot detect version from the supplied server response" )

	def __str__( self ):
		return self.user_agent

	def verbose_str( self ):
		return "{} {}/{} {} v{}.{}.{}.{}, engine v{}, ui v{}".format( self.user_agent, self.device_id, self.peer_id, self.product, self.major,
		                                                              self.middle, self.minor, self.build, self.engine, self.ui )
