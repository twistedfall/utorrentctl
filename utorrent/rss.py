"""
rss
"""

from datetime import datetime
from utorrent import _get_external_attrs


class Feed:
	feed_id = 0
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
		return "{: <3} {: <3} {}".format( self.feed_id, "on" if self.enabled else "off", self.url )

	def verbose_str( self ):
		return "{} ({}/{}) update: {}".format(
			str( self ), len( [x for x in self.entries if x.in_history] ), len( self.entries ), self.next_update
		)

	def fill( self, feed ):
		self.feed_id, self.enabled, self.use_feed_title, self.user_selected, self.programmed, \
		self.download_state, self.url, self.next_update = feed[0:8]
		self.next_update = datetime.fromtimestamp( self.next_update )
		self.entries = []
		for e in feed[8]:
			self.entries.append( FeedEntry( e ) )

	@classmethod
	def get_readonly_attrs( cls ):
		return "id", "use_feed_title", "user_selected", "programmed", "download_state", "next_update", "entries"

	@classmethod
	def get_writeonly_attrs( cls ):
		return "download_dir", "alias", "subscribe", "smart_filter"

	@classmethod
	def get_public_attrs( cls ):
		return tuple( set( _get_external_attrs( cls ) ) - set( cls.get_readonly_attrs( ) ) )


class FeedEntry:
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
			self.timestamp = datetime.fromtimestamp( self.timestamp )
		except ValueError: # utorrent 2.2 sometimes gives too large timestamp
			pass


class Filter:
	filter_id = 0
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
		return "{: <3} {: <3} {}".format( self.filter_id, "on" if self.enabled else "off", self.name )

	def verbose_str( self ):
		return "{} {} -> {}: +{}-{}".format( str( self ), self.filter, self.save_in, self.filter,
		                                     self.not_filter )

	def fill( self, filter_props ):
		self.filter_id, self.flags, self.name, self.filter, self.not_filter, self.save_in, self.feed_id, \
		self.quality, self.label, self.postpone_mode, self.last_match, self.smart_ep_filter, \
		self.repack_ep_filter, self.episode, self.episode_filter, self.resolving_candidate = filter_props
		self.postpone_mode = bool( self.postpone_mode )

	@classmethod
	def get_readonly_attrs( cls ):
		return "id", "flags", "last_match", "resolving_candidate", "enabled"

	@classmethod
	def get_writeonly_attrs( cls ):
		return "prio", "add_stopped"

	@classmethod
	def get_public_attrs( cls ):
		return tuple( set( _get_external_attrs( cls ) ) - set( cls.get_readonly_attrs( ) ) )

	@property
	def enabled( self ):
		return bool( self.flags & 1 )
