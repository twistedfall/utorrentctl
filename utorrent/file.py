"""
File
"""

import utorrent.priority
import utorrent.uTorrent

class File:
	_utorrent = None

	hash_code = ""
	index = 0
	file_hash = ""
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
		self.hash_code = parent_hash
		self.index = index
		self.file_hash = "{}.{}".format( self.hash_code, self.index )
		if file:
			self.fill( file )

	def __str__( self ):
		return "{} {}".format( self.file_hash, self.name )

	def verbose_str( self ):
		return "{: <44} [{: <15}] {: >5}% ({: >9} / {: >9}) {}".format( self.file_hash, self.priority, self.progress,
		                                                                self.downloaded_h, self.size_h, self.name )

	def fill( self, file ):
		self.name, self.size, self.downloaded, priority = file[:4]
		self.priority = utorrent.priority.Priority( priority )
		if self.size == 0:
			self.progress = 100
		else:
			self.progress = round( float( self.downloaded ) / self.size * 100, 1 )
		self.size_h = utorrent.human_size( self.size )
		self.downloaded_h = utorrent.human_size( self.downloaded )

	def set_priority( self, priority ):
		self._utorrent.file_set_priority( { self.file_hash: priority } )


class File_API2( File ):
	def fill( self, file ):
		File.fill( self, file[:4] )
