"""
JobInfo
"""

import utorrent

class JobInfo:

	_utorrent = None

	hash_code = ""
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

	def __init__( self, utorrent, torrent_hash = None, jobinfo = None ):
		self._utorrent = utorrent
		self.hash_code = torrent_hash
		if jobinfo:
			self.fill( jobinfo )

	def __str__( self ):
		return "Limits D:{} U:{}".format( self.dlrate, self.ulrate )

	def verbose_str( self ):
		return str( self ) + "  Superseed:{}  DHT:{}  PEX:{}  Queuing override:{}  Seed ratio:{}  Seed time:{}".format(
			self._tribool_status_str( self.superseed ), self._tribool_status_str( self.dht ),
			self._tribool_status_str( self.pex ), self._tribool_status_str( self.seed_override ), self.seed_ratio,
			utorrent.human_time_delta( self.seed_time )
		)

	def fill( self, jobinfo ):
		self.hash_code = jobinfo["hash"]
		self.trackers = jobinfo["trackers"].strip().split( "\r\n\r\n" )
		self.ulrate = jobinfo["ulrate"]
		self.ulrate_h = utorrent.human_size( self.ulrate ) + "/s"
		self.dlrate = jobinfo["dlrate"]
		self.dlrate_h = utorrent.human_size( self.dlrate ) + "/s"
		self.superseed = jobinfo["superseed"]
		self.dht = jobinfo["dht"]
		self.pex = jobinfo["pex"]
		self.seed_override = jobinfo["seed_override"]
		self.seed_ratio = jobinfo["seed_ratio"]
		self.seed_time = jobinfo["seed_time"]

	@classmethod
	def get_public_attrs( cls ):
		return utorrent._get_external_attrs( cls )

	def _tribool_status_str( self, status ):
		return "not allowed" if status == -1 else ( "disabled" if status == 0 else "enabled" )
