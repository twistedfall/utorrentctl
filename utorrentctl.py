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

=====

	utorrentctl - uTorrent cli remote control utility

"""
import datetime
import os
import optparse
import sys
import utorrent.rss as rss
from utorrent.uTorrent import Desktop, Falcon, LinuxServer
from utorrent.connection import Connection
from utorrent import uTorrentError
import utorrent as utorrent_module


level1 = "   "
level2 = level1 * 2
level3 = level1 * 3


def print_console( *objs, sep = " ", end = "\n", file = sys.stdout ):
	print( *map( lambda x: str( x ).encode( sys.stdout.encoding, "replace" ).decode( sys.stdout.encoding ), objs ), sep = sep, end = end, file = file )


def get_config_dir():
	config_home = os.getenv( "XDG_CONFIG_HOME" )
	if config_home is None:
		config_home = os.path.expanduser( "~" ) + os.path.sep + ".config"
	return config_home + os.path.sep + "utorrentctl" + os.path.sep


def get_cache_dir():
	config_home = os.getenv( "XDG_CACHE_HOME" )
	if config_home is None:
		config_home = os.path.expanduser( "~" ) + os.path.sep + ".cache"
	return config_home + os.path.sep + "utorrentctl" + os.path.sep


def dump_writer( obj, props, level1 = level2, level2 = level3 ):
	for name in sorted( props ):
		print_console( level1 + name, end = "" )
		try:
			value = getattr( obj, name )
			if utorrent_module.is_list_type( value ):
				print_console( ":" )
				for item in value:
					if opts.verbose and hasattr( item, "verbose_str" ):
						item_str = item.verbose_str( )
					else:
						item_str = str( item )
					print_console( level2 + item_str )
			else:
				if hasattr( obj, name + "_h" ):
					print_console( " = {} ({})".format( value, getattr( obj, name + "_h" ) ) )
				else:
					print_console( " = {}".format( value ) )
		except AttributeError:
			print_console( )


def filetree_writer( tree, cur_level = 0 ):
	for name, leaf in tree.items( ):
		if isinstance( leaf, dict ):
			print_console( level1 * cur_level + "+ " + name )
			filetree_writer( leaf, cur_level + 1 )
		else:
			print_console( level1 * cur_level + ( leaf.verbose_str( ) if opts.verbose else str( leaf ) ) )


try:
	sys.path.append( get_config_dir( ) )
	from config import utorrentcfg
except ImportError:
	utorrentcfg = { "host": None, "login": None, "password": None }

if not "api" in utorrentcfg:
	utorrentcfg["api"] = None

if not "default_torrent_format" in utorrentcfg:
	utorrentcfg["default_torrent_format"] = None

parser = optparse.OptionParser( )
parser.add_option( "-H", "--host", dest = "host", help = "host of uTorrent (hostname:port)" )
parser.add_option( "-U", "--user", dest = "user", help = "WebUI login" )
parser.add_option( "-P", "--password", dest = "password", help = "WebUI password" )
parser.add_option( "--api", dest = "api",
                   help = "Disable autodetection of server version and force specific API: linux, desktop (2.x), falcon (3.x)" )
parser.add_option( "-n", "--nv", "--no-verbose", action = "store_false", dest = "verbose", default = True,
                   help = "show shortened info in most cases (quicker, saves network traffic)" )
parser.add_option( "--server-version", action = "store_const", dest = "action", const = "server_version", help = "print uTorrent server version" )
parser.add_option( "-l", "--list-torrents", action = "store_const", dest = "action", const = "torrent_list", help = "list all torrents" )
parser.add_option( "-c", "--active", action = "store_true", dest = "active", default = False,
                   help = "when listing torrents display only active ones (speed > 0)" )
parser.add_option( "-f", "--format", default = utorrentcfg["default_torrent_format"], dest = "format",
                   help = "display torrent list in specific format, e.g. '{hash} {name} {ratio}', use --dump to view full list of available fields + peer_info (display seeds or peers depending on progress)" )
parser.add_option( "--label", dest = "label", help = "when listing torrents display only ones with specified label" )
parser.add_option( "-s", "--sort", default = "name", dest = "sort_field", help = "sort torrents, use --dump to view full list of available fields" )
parser.add_option( "--desc", action = "store_true", dest = "sort_desc", default = False, help = "sort torrents in descending order" )
parser.add_option( "-a", "--add-file", action = "store_const", dest = "action", const = "add_file",
                   help = "add torrents specified by local file names, with force flag will force-start torrent after adding (filename filename ...)" )
parser.add_option( "-u", "--add-url", action = "store_const", dest = "action", const = "add_url",
                   help = "add torrents specified by urls, with force flag will force-start torrent after adding magnet url (url url ...)" )
parser.add_option( "--dir", dest = "download_dir",
                   help = "directory to download added torrent, absolute or relative to current download dir (for add, download)" )
parser.add_option( "--settings", action = "store_const", dest = "action", const = "settings_get",
                   help = "show current server settings, optionally you can use specific setting keys (name name ...)" )
parser.add_option( "--set", action = "store_const", dest = "action", const = "settings_set",
                   help = "assign settings value (key1=value1 key2=value2 ...)" )
parser.add_option( "--start", action = "store_const", dest = "action", const = "torrent_start", help = "start torrents (hash hash ...)" )
parser.add_option( "--stop", action = "store_const", dest = "action", const = "torrent_stop", help = "stop torrents (hash hash ...)" )
parser.add_option( "--pause", action = "store_const", dest = "action", const = "torrent_pause", help = "pause torrents (hash hash ...)" )
parser.add_option( "--resume", action = "store_const", dest = "action", const = "torrent_resume", help = "resume torrents (hash hash ...)" )
parser.add_option( "--recheck", action = "store_const", dest = "action", const = "torrent_recheck",
                   help = "recheck torrents, torrent will be stopped and restarted if needed (hash hash ...)" )
parser.add_option( "--remove", action = "store_const", dest = "action", const = "torrent_remove", help = "remove torrents (hash hash ...)" )
parser.add_option( "--all", action = "store_true", dest = "all", default = False,
                   help = "applies action to all torrents/rss feeds (for start, stop, pause, resume, recheck, rss-update)" )
parser.add_option( "-F", "--force", action = "store_true", dest = "force", default = False,
                   help = "forces current command (for start, recheck (with all), remove, add-file, add-url, download)" )
parser.add_option( "--data", action = "store_true", dest = "with_data", default = False,
                   help = "when removing torrent also remove its data (for remove, also enabled by --force)" )
parser.add_option( "--torrent", action = "store_true", dest = "with_torrent", default = False,
                   help = "when removing torrent also remove its torrent file (for remove with uTorrent server, also enabled by --force)" )
parser.add_option( "-i", "--info", action = "store_const", dest = "action", const = "torrent_info",
                   help = "show info and file/trackers list for the specified torrents (hash hash ...)" )
parser.add_option( "--dump", action = "store_const", dest = "action", const = "torrent_dump",
                   help = "show full torrent info in key=value view (hash hash ...)" )
parser.add_option( "--stats", action = "store_const", dest = "action", const = "stats",
                   help = "display server download/upload statistics (uTorrent server only)" )
parser.add_option( "--reset-stats", action = "store_const", dest = "action", const = "reset_stats",
                   help = "reset server download/upload statistics (uTorrent server only)" )
parser.add_option( "--download", action = "store_const", dest = "action", const = "download",
                   help = "downloads specified file, with force flag will overwrite all existing files (hash.file_index)" )
parser.add_option( "--prio", action = "store_const", dest = "action", const = "set_file_priority",
                   help = "sets specified file priority, if you omit file_index then priority will be set for all files (hash[.file_index][=prio] hash[.file_index][=prio] ...) prio=0..3, if not specified then 2 is by default" )
parser.add_option( "--set-props", action = "store_const", dest = "action", const = "set_props",
                   help = "change properties of torrent, e.g. label; use --dump to view them (hash.prop=value hash.prop=value ...)" )
parser.add_option( "--rss-list", action = "store_const", dest = "action", const = "rss_list", help = "list all rss feeds and filters" )
parser.add_option( "--rss-add", action = "store_const", dest = "action", const = "rss_add",
                   help = "add rss feeds specified by urls (feed_url feed_url ...)" )
parser.add_option( "--rss-update", action = "store_const", dest = "action", const = "rss_update",
                   help = "forces update of the specified rss feeds (feed_id feed_id ...)" )
parser.add_option( "--rss-remove", action = "store_const", dest = "action", const = "rss_remove",
                   help = "removes rss feeds specified by ids (feed_id feed_id ...)" )
parser.add_option( "--rss-dump", action = "store_const", dest = "action", const = "rss_dump",
                   help = "show full rss feed info in key=value view (feed_id feed_id ...)" )
parser.add_option( "--rss-set-props", action = "store_const", dest = "action", const = "rss_set_props",
                   help = "change properties of rss feed; use --rss-dump to view them (feed_id.prop=value feed_id.prop=value ...)" )
parser.add_option( "--rssfilter-add", action = "store_const", dest = "action", const = "rssfilter_add",
                   help = "add filters for specified rss feeds (feed_id feed_id ...)" )
parser.add_option( "--rssfilter-remove", action = "store_const", dest = "action", const = "rssfilter_remove",
                   help = "removes rss filter specified by ids (filter_id filter_id ...)" )
parser.add_option( "--rssfilter-dump", action = "store_const", dest = "action", const = "rssfilter_dump",
                   help = "show full rss filter info in key=value view (filter_id filter_id ...)" )
parser.add_option( "--rssfilter-set-props", action = "store_const", dest = "action", const = "rssfilter_set_props",
                   help = "change properties of rss filter; use --rssfilter-dump to view them (filter_id.prop=value filter_id.prop=value ...)" )
parser.add_option( "--magnet", action = "store_const", dest = "action", const = "get_magnet",
                   help = "generate magnet link for the specified torrents (hash hash ...)" )
parser.add_option( "--limit", dest = "limit", default = 0, help = "limit the number of records to return, 0 returns all, default is 0" )
opts, args = parser.parse_args( )

try:

	if opts.host is None: # we didn't supply host in command line => load auth data from config
		opts.host = utorrentcfg["host"]
		if opts.user is None:
			opts.user = utorrentcfg["login"]
		if opts.password is None:
			opts.password = utorrentcfg["password"]
		if opts.api is None:
			opts.api = utorrentcfg["api"]

	utorrent = None
	if opts.action is not None:
		utorrent = Connection( opts.host, opts.user, opts.password ).utorrent( opts.api )

	if opts.action == "server_version":
		print_console( utorrent.version( ).verbose_str( ) if opts.verbose else utorrent.version( ) )

	elif opts.action == "torrent_list":
		total_ul, total_dl, count, total_size = 0, 0, 0, 0
		opts.sort_field = opts.sort_field.lower( )
		# ensure that int is returned
		opts.limit = int( opts.limit )
		if not opts.sort_field in utorrent.TorrentClass.get_public_attrs( ) + utorrent.TorrentClass.get_readonly_attrs( ):
			opts.sort_field = "name"
		for h, t in sorted( utorrent.torrent_list( ).items( ), key = lambda x: getattr( x[1], opts.sort_field ), reverse = opts.sort_desc ):
			if not opts.active or opts.active and ( t.ul_speed > 0 or t.dl_speed > 0 ): # handle --active
				if opts.label is None or opts.label == t.label: # handle --label
					count += 1
					if opts.limit > 0 and count > opts.limit:
						break
					total_size += t.progress / 100 * t.size
					if opts.verbose:
						print_console( t.verbose_str( opts.format ) )
						total_ul += t.ul_speed
						total_dl += t.dl_speed
					else:
						print_console( t )
		if opts.verbose:
			print_console( "Total speed: D:{}/s U:{}/s  count: {}  size: {}".format(
				utorrent_module.human_size( total_dl ), utorrent_module.human_size( total_ul ),
				count, utorrent_module.human_size( total_size )
			) )

	elif opts.action == "add_file":
		for i in args:
			print_console( "Submitting {}...".format( i ) )
			hsh = utorrent.torrent_add_file( i, opts.download_dir )
			print_console( level1 + "Info hash = {}".format( hsh ) )
			if opts.force:
				print_console( level1 + "Forcing start..." )
				utorrent.torrent_start( hsh, True )

	elif opts.action == "add_url":
		for i in args:
			print_console( "Submitting {}...".format( i ) )
			hsh = utorrent.torrent_add_url( i, opts.download_dir )
			if hsh is not None:
				print_console( level1 + "Info hash = {}".format( hsh ) )
				if opts.force:
					print_console( level1 + "Forcing start..." )
					utorrent.torrent_start( hsh, True )

	elif opts.action == "settings_get":
		for i in sorted( utorrent.settings_get( ).items( ) ):
			if len( args ) == 0 or i[0] in args:
				print_console( "{} = {}".format( *i ) )

	elif opts.action == "settings_set":
		utorrent.settings_set( { k: v for k, v in [i.split( "=" ) for i in args] } )

	elif opts.action == "torrent_start":
		torr_list = None
		if opts.all:
			torr_list = utorrent.torrent_list( )
			args = torr_list.keys( )
			print_console( "Starting all torrents..." )
		else:
			if opts.verbose:
				torrs = utorrent.resolve_torrent_hashes( args, torr_list )
			else:
				torrs = args
			print_console( "Starting " + ", ".join( torrs ) + "..." )
		utorrent.torrent_start( args, opts.force )

	elif opts.action == "torrent_stop":
		torr_list = None
		if opts.all:
			torr_list = utorrent.torrent_list( )
			args = torr_list.keys( )
			print_console( "Stopping all torrents..." )
		else:
			if opts.verbose:
				torrs = utorrent.resolve_torrent_hashes( args, torr_list )
			else:
				torrs = args
			print_console( "Stopping " + ", ".join( torrs ) + "..." )
		utorrent.torrent_stop( args )

	elif opts.action == "torrent_resume":
		torr_list = None
		if opts.all:
			torr_list = utorrent.torrent_list( )
			args = torr_list.keys( )
			print_console( "Resuming all torrents..." )
		else:
			if opts.verbose:
				torrs = utorrent.resolve_torrent_hashes( args, torr_list )
			else:
				torrs = args
			print_console( "Resuming " + ", ".join( torrs ) + "..." )
		utorrent.torrent_resume( args )

	elif opts.action == "torrent_pause":
		torr_list = None
		if opts.all:
			torr_list = utorrent.torrent_list( )
			args = torr_list.keys( )
			print_console( "Pausing all torrents..." )
		else:
			if opts.verbose:
				torrs = utorrent.resolve_torrent_hashes( args, torr_list )
			else:
				torrs = args
			print_console( "Pausing " + ", ".join( torrs ) + "..." )
		utorrent.torrent_pause( args )

	elif opts.action == "torrent_recheck":
		torr_list = utorrent.torrent_list( )
		if opts.all:
			if opts.force:
				args = torr_list.keys( )
				print_console( "Rechecking all torrents..." )
			else:
				raise uTorrentError( "Refusing to recheck all torrents! Please specify --force to override" )
		else:
			if opts.verbose:
				torrs = utorrent.resolve_torrent_hashes( args, torr_list )
			else:
				torrs = args
			print_console( "Rechecking " + ", ".join( torrs ) + "..." )
		for hsh in args:
			if hsh in torr_list:
				torr = torr_list[hsh]
				torr.stop( )
				torr.recheck( )
				if ( torr.status.started and not torr.status.paused ) or torr.status.error:
					torr.start( not ( torr.status.queued or torr.status.error ) )

	elif opts.action == "torrent_remove":
		if opts.verbose:
			torrs = utorrent.resolve_torrent_hashes( args )
		else:
			torrs = args
		print_console( "Removing " + ", ".join( torrs ) + "..." )
		if utorrent.api_version == LinuxServer.api_version:
			utorrent.torrent_remove( args, opts.with_data or opts.force, opts.with_torrent or opts.force )
		else:
			utorrent.torrent_remove( args, opts.with_data or opts.force )

	elif opts.action == "torrent_info":
		tors = utorrent.torrent_list( )
		files = utorrent.file_list( args )
		infos = utorrent.torrent_info( args )
		for hsh, fls in files.items( ):
			print_console( tors[hsh].verbose_str( opts.format ) if opts.verbose else tors[hsh] )
			print_console( level1 + ( infos[hsh].verbose_str( ) if opts.verbose else str( infos[hsh] ) ) )
			print_console( level1 + "Files ({}):".format( len( fls ) ) )
			for f in fls:
				print_console( level2 + ( f.verbose_str( ) if opts.verbose else str( f ) ) )
			print_console( level1 + "Trackers:" )
			for tr in infos[hsh].trackers:
				print_console( level2 + tr )

	elif opts.action == "torrent_dump":
		tors = utorrent.torrent_list( )
		infos = utorrent.torrent_info( args )
		for hsh, info in infos.items( ):
			print_console( tors[hsh].verbose_str( opts.format ) if opts.verbose else tors[hsh] )
			print_console( level1 + "Properties:" )
			dump_writer( tors[hsh], tors[hsh].get_public_attrs( ) )
			dump_writer( info, info.get_public_attrs( ) )
			print_console( level1 + "Read-only:" )
			dump_writer( tors[hsh], tors[hsh].get_readonly_attrs( ) )

	elif opts.action == "stats":
		res = utorrent.xfer_history_get( )
		excl_local = utorrent.settings_get( )["net.limit_excludeslocal"]
		torrents = utorrent.torrent_list( )
		today_start = datetime.datetime.now( ).replace( hour = 0, minute = 0, second = 0, microsecond = 0 )
		period = len( res["daily_download"] )
		period_start = today_start - datetime.timedelta( days = period - 1 )

		down_total_local = sum( res["daily_local_download"] )
		down_total = sum( res["daily_download"] ) - ( down_total_local if excl_local else 0 )
		up_total_local = sum( res["daily_local_upload"] )
		up_total = sum( res["daily_upload"] ) - ( down_total_local if excl_local else 0 )
		period_added_torrents = { k: v for k, v in torrents.items( ) if v.added_on >= period_start }
		period_completed_torrents = { k: v for k, v in torrents.items( ) if v.completed_on >= period_start }
		print_console( "Last {} days:".format( period ) )
		print_console(
			level1 + "Downloaded: {} (+{} local)".format( utorrent_module.human_size( down_total ), utorrent_module.human_size( down_total_local ) ) )
		print_console(
			level1 + "  Uploaded: {} (+{} local)".format( utorrent_module.human_size( up_total ), utorrent_module.human_size( up_total_local ) ) )
		print_console( level1 + "     Total: {} (+{} local)".format( utorrent_module.human_size( down_total + up_total ),
		                                                             utorrent_module.human_size( down_total_local + up_total_local ) ) )
		print_console( level1 + "Ratio: {:.2f}".format( up_total / down_total ) )
		print_console( level1 + "Added torrents: {}".format( len( period_added_torrents ) ) )
		print_console( level1 + "Completed torrents: {}".format( len( period_completed_torrents ) ) )

		down_day_local = res["daily_local_download"][0]
		down_day = res["daily_download"][0] - ( down_day_local if excl_local else 0 )
		up_day_local = res["daily_local_upload"][0]
		up_day = res["daily_upload"][0] - ( up_day_local if excl_local else 0 )
		today_added_torrents = { k: v for k, v in torrents.items( ) if v.added_on >= today_start }
		today_completed_torrents = { k: v for k, v in torrents.items( ) if v.completed_on >= today_start }
		print_console( "Today:" )
		print_console(
			level1 + "Downloaded: {} (+{} local)".format( utorrent_module.human_size( down_day ), utorrent_module.human_size( down_day_local ) ) )
		print_console(
			level1 + "  Uploaded: {} (+{} local)".format( utorrent_module.human_size( up_day ), utorrent_module.human_size( up_day_local ) ) )
		print_console( level1 + "     Total: {} (+{} local)".format( utorrent_module.human_size( down_day + up_day ),
		                                                             utorrent_module.human_size( down_day_local + up_day_local ) ) )
		print_console( level1 + "Ratio: {:.2f}".format( up_day / down_day ) )
		print_console( level1 + "Added torrents: {}".format( len( today_added_torrents ) ) )
		print_console( level1 + "Completed torrents: {}".format( len( today_completed_torrents ) ) )

	elif opts.action == "reset_stats":
		res = utorrent.xfer_history_reset( )

	elif opts.action == "download":
		if utorrent.api_version < Falcon.api_version:
			raise uTorrentError( "Downloading files only supported for uTorrent 3.x and uTorrent Server" )
		for filespec in args:
			parent_hash, indices = Desktop.parse_hash_prop( filespec )
			files = utorrent.file_list( parent_hash )
			if len( files ) == 0:
				print_console( "Specified torrent or file does not exist" )
				sys.exit( 1 )
			base_dir = opts.download_dir if opts.download_dir else "."
			make_tree = False # single file download => place it in the base directory
			torrents = None
			if indices == None:
				indices = [i for i, f in enumerate( files[parent_hash] ) if f.progress == 100 and f.priority.value > 0]
				if len( files[parent_hash] ) > 1:
					make_tree = True # whole torrent download => keep directory tree
				torrents = utorrent.torrent_list( )
			else:
				indices = ( int( indices ), )

			def progress( range_start, loaded, total ):
				global bar_width, tick_size, start_time
				if range_start is None:
					range_start = 0
				progr = int( round( ( range_start + loaded ) / tick_size ) ) if tick_size > 0 else 1
				delta = datetime.datetime.now( ) - start_time
				delta = delta.seconds + delta.microseconds / 1000000
				if opts.verbose:
					print_console( "[{}{}] {} {}/s eta: {}{}".format(
						"*" * progr, "_" * ( bar_width - progr ),
						utorrent_module.human_size( total ),
						utorrent_module.human_size( loaded / delta ),
						utorrent_module.human_time_delta( ( total - loaded ) / ( loaded / delta ) if loaded > 0 else 0 ),
						" " * 25
					), sep = "", end = ""
					)
					print_console( "\b" * ( bar_width + 70 ), end = "" )
					sys.stdout.flush( )

			for index in indices:
				if make_tree:
					filename = base_dir + os.path.sep + torrents[parent_hash].name + os.path.sep + os.path.normpath( files[parent_hash][index].name )
				else:
					filename = base_dir + os.path.sep + utorrent.pathmodule.basename( files[parent_hash][index].name )
				verb = "Downloading"
				file = None
				range_start = None
				if os.path.exists( filename ):
					if opts.force:
						file = open( filename, "wb" )
						file.truncate( )
					elif os.path.getsize( filename ) == files[parent_hash][index].size:
						print_console( "Skipping {}, already exists, specify --force to overwrite...".format( filename ) )
					else:
						verb = "Resuming download"
						file = open( filename, "ab" )
						range_start = os.path.getsize( filename )
				else:
					try:
						os.makedirs( os.path.dirname( filename ) )
					except OSError as e:
						if e.args[0] != 17: # "File exists" => dir exists, by design, ignore
							raise e
					file = open( filename, "wb" )
				if file is not None:
					print_console( "{} {}...".format( verb, filename ) )
					bar_width = 50
					tick_size = files[parent_hash][index].size / bar_width
					start_time = datetime.datetime.now( )
					utorrent.file_get( "{}.{}".format( parent_hash, index ), file, range_start = range_start, progress_cb = progress )
					if opts.verbose:
						print_console( "" )

	elif opts.action == "set_file_priority":
		prios = { }
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
			props.append( { hsh: { name: value } } )
		utorrent.torrent_set_props( props )

	elif opts.action == "rss_list":
		rssfeeds = { }
		rssfilters = { }
		utorrent.torrent_list( None, rssfeeds, rssfilters )
		feed_id_index = { }
		for filter_id, filter_props in rssfilters.items( ):
			if not filter_props.feed_id in feed_id_index:
				feed_id_index[filter_props.feed_id] = []
			feed_id_index[filter_props.feed_id].append( filter_props )
		print_console( "Feeds:" )
		for feed_id, feed in rssfeeds.items( ):
			print_console( level1 + ( feed.verbose_str( ) if opts.verbose else str( feed ) ) )
			if feed_id in feed_id_index:
				print_console( level1 + "Filters:" )
				for filter_props in feed_id_index[feed_id]:
					print_console( level2 + ( filter_props.verbose_str( ) if opts.verbose else str( filter_props ) ) )
		if -1 in feed_id_index and len( feed_id_index[-1] ) > 0:
			print_console( "Global filters:" )
			for filter_props in feed_id_index[-1]:
				print_console( level1 + ( filter_props.verbose_str( ) if opts.verbose else str( filter_props ) ) )

	elif opts.action == "rss_add":
		for url in args:
			print_console( "Adding {}...".format( url ) )
			feed_id = utorrent.rss_add( url )
			if feed_id != -1:
				print_console( level1 + "Feed id = {} (add a filter to it to make it download something)".format( feed_id ) )
			else:
				print_console( level1 + "Failed to add feed" )

	elif opts.action == "rss_update":
		feed_list = None
		if opts.all:
			feed_list = utorrent.rss_list( )
			args = list( map( str, feed_list.keys( ) ) )
			print_console( "Updating all rss feeds..." )
		else:
			if opts.verbose:
				feeds = utorrent.resolve_feed_ids( args, feed_list )
			else:
				feeds = args
			print_console( "Updating " + ", ".join( feeds ) + "..." )
		for feed_id in args:
			utorrent.rss_update( feed_id, { "update": 1 } )

	elif opts.action == "rss_remove":
		if opts.verbose:
			feeds = utorrent.resolve_feed_ids( args )
		else:
			feeds = args
		print_console( "Removing " + ", ".join( feeds ) + "..." )
		for feed_id in args:
			utorrent.rss_remove( feed_id )

	elif opts.action == "rss_dump":
		feeds = utorrent.rss_list( )
		for feed_id, feed in { i: f for i, f in feeds.items( ) if str( i ) in args }.items( ):
			print_console( feed.url )
			print_console( level1 + "Properties:" )
			dump_writer( feed, feed.get_public_attrs( ) )
			print_console( level1 + "Read-only:" )
			dump_writer( feed, feed.get_readonly_attrs( ) )
			print_console( level1 + "Write-only:" )
			dump_writer( feed, feed.get_writeonly_attrs( ) )

	elif opts.action == "rss_set_props":
		for a in args:
			feed_id, value = a.split( "=", 1 )
			feed_id, name = feed_id.split( ".", 1 )
			if name in rss.Feed.get_public_attrs( ) or name in rss.Feed.get_writeonly_attrs( ):
				utorrent.rss_update( feed_id, { name: value } )

	elif opts.action == "rssfilter_add":
		for feed_id in args:
			print_console( "Adding filter for feed {}...".format( feed_id ) )
			filter_id = utorrent.rssfilter_add( feed_id )
			if filter_id != -1:
				print_console( level1 + "Filter id = {}".format( filter_id ) )
			else:
				print_console( level1 + "Failed to add filter" )

	elif opts.action == "rssfilter_remove":
		if opts.verbose:
			feeds = utorrent.resolve_filter_ids( args )
		else:
			feeds = args
		print_console( "Removing " + ", ".join( feeds ) + "..." )
		for filter_id in args:
			utorrent.rssfilter_remove( filter_id )

	elif opts.action == "rssfilter_dump":
		filters = utorrent.rssfilter_list( )
		for filter_id, filter_props in { i: f for i, f in filters.items( ) if str( i ) in args }.items( ):
			print_console( filter_props.name )
			print_console( level1 + "Properties:" )
			dump_writer( filter_props, filter_props.get_public_attrs( ) )
			print_console( level1 + "Read-only:" )
			dump_writer( filter_props, filter_props.get_readonly_attrs( ) )
			print_console( level1 + "Write-only:" )
			dump_writer( filter_props, filter_props.get_writeonly_attrs( ) )

	elif opts.action == "rssfilter_set_props":
		for a in args:
			filter_id, value = a.split( "=", 1 )
			filter_id, name = filter_id.split( ".", 1 )
			if name in rss.Filter.get_public_attrs( ) or rss.Filter.get_writeonly_attrs( ):
				utorrent.rssfilter_update( filter_id, { name.replace( "_", "-" ): value } )

	elif opts.action == "get_magnet":
		if opts.verbose:
			tors = utorrent.torrent_list( )
		for hsh, lnk in utorrent.torrent_get_magnet( args ).items( ):
			print_console( tors[hsh] if opts.verbose else hsh )
			print_console( level1 + lnk )

	else:
		parser.print_help( )

except uTorrentError as e:
	print_console( e )
	sys.exit( 1 )
