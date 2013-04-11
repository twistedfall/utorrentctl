"""
Torrent
"""
from datetime import datetime

import string
import utorrent


class Torrent:
	_utorrent = None
	""" :type: utorrent.uTorrent.Desktop """

	hash_code = ""
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
	"status": "{status: <15}",
	"name": "{name: <60}",
	"size": "{size_h: >9}",
	"progress": "{progress: >5.1f}",
	"downloaded": "{downloaded_h: >9}",
	"uploaded": "{uploaded_h: >9}",
	"ratio": "{ratio: <6.2f}",
	"dl_speed": "{dl_speed_h: >12}",
	"ul_speed": "{ul_speed_h: >12}",
	"eta": "{eta_h: <7}",
	"label": "{label}",
	"peers_connected": "{peers_connected: <4}",
	"peers_total": "{peers_total: <5}",
	"seeds_connected": "{seeds_connected: <4}",
	"seeds_total": "{seeds_total: <5}",
	"peer_info": "{peer_info: <7}",
	"availability": "{availability_h: >5.2}",
	"dl_remain": "{dl_remain_h: >9}",
	}

	def __init__( self, utorrent_obj, torrent = None ):
		"""
		:type utorrent_obj: utorrent.uTorrent.Desktop
		:type torrent: dict
		"""
		self._utorrent = utorrent_obj
		if torrent:
			self.fill( torrent )

	def __str__( self ):
		return "{} {}".format( self.hash_code, self.name )

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
		formatter = string.Formatter( )
		for literal_text, field_name, format_spec, conversion in formatter.parse( format_string ):
			elem = { "before": literal_text, "value": "" }
			if field_name is not None:
				def_field_name, def_format_spec, def_conversion = None, " <20", None
				if field_name in self._default_format_specs:
					def_field_name, def_format_spec, def_conversion = next( formatter.parse( self._default_format_specs[field_name] ) )[1:4]
				val = formatter.get_field( field_name if def_field_name is None else def_field_name, None, args )[0]
				val = formatter.convert_field( val, conversion if conversion is not None else def_conversion )
				val = formatter.format_field( val, format_spec if format_spec != "" else def_format_spec )
				elem["value"] = val
			out.append( elem )
		return out

	def _format_to_str( self, format_res ):
		out = ""
		for i in format_res:
			out += i["before"] + i["value"]
		return out.strip( )

	def verbose_str( self, format_string = None ):
		return self._format_to_str( self._process_format( self._default_format if format_string is None else format_string ) )

	def fill( self, torrent ):
		self.hash_code, status, self.name, self.size, progress, self.downloaded, \
		self.uploaded, ratio, self.ul_speed, self.dl_speed, self.eta, self.label, \
		self.peers_connected, self.peers_total, self.seeds_connected, self.seeds_total, \
		self.availability, self.queue_order, self.dl_remain = torrent
		self._utorrent.check_hash( self.hash_code )
		self.progress = progress / 10.
		self.ratio = ratio / 1000.
		self.status = TorrentStatus( status, self.progress )
		self.size_h = utorrent.human_size( self.size )
		self.uploaded_h = utorrent.human_size( self.uploaded )
		self.downloaded_h = utorrent.human_size( self.downloaded )
		self.ul_speed_h = utorrent.human_size( self.ul_speed ) + "/s"
		self.dl_speed_h = utorrent.human_size( self.dl_speed ) + "/s"
		self.eta_h = utorrent.human_time_delta( self.eta )
		self.availability_h = self.availability / 65535.
		self.dl_remain_h = utorrent.human_size( self.dl_remain )

	@classmethod
	def get_readonly_attrs( cls ):
		return tuple( set( utorrent._get_external_attrs( cls ) ) - { "label" } )

	@classmethod
	def get_public_attrs( cls ):
		return tuple( set( utorrent._get_external_attrs( cls ) ) - set( cls.get_readonly_attrs( ) ) )

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
	_utorrent = None
	""" :type: utorrent.uTorrent.Falcon """
	url = ""
	rss_url = ""
	status_message = ""
	_unk_hash = ""
	added_on = 0
	completed_on = 0
	_unk_str = 0
	download_dir = ""

	def __init__( self, utorrent_obj, torrent = None ):
		Torrent.__init__( self, utorrent_obj, torrent )
		self._default_format_specs["status"] = "{status_message: <15}"
		self._default_format_specs["completed_on"] = "{completed_on!s}"
		self._default_format_specs["added_on"] = "{added_on!s}"

	def fill( self, torrent ):
		Torrent.fill( self, torrent[0:19] )
		self.url, self.rss_url, self.status_message, self._unk_hash, self.added_on, \
		self.completed_on, self._unk_str, self.download_dir = torrent[19:27]
		self.added_on = datetime.fromtimestamp( self.added_on )
		self.completed_on = datetime.fromtimestamp( int( self.completed_on ) )

	def remove( self, with_data = False, with_torrent = False ):
		return self._utorrent.torrent_remove( self, with_data, with_torrent )


class Label:
	name = ""
	torrent_count = 0

	def __init__( self, label ):
		self.name, self.torrent_count = label

	def __str__( self ):
		return "{} ({})".format( self.name, self.torrent_count )


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
				# 				else:
				# 					return "Stopped"
		return "Stopped"

	def __lt__( self, other ):
		return self._value < other._value
