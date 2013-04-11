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

utorrent - uTorrent remote control library

"""

import re
import urllib.parse


class uTorrentError( Exception ):
	"""
	uTorrent specific exception
	"""
	pass


def bdecode( data, str_encoding = "utf8" ):
	"""
	Decode binary string to object using bencode encoding.
	http://en.wikipedia.org/wiki/Bencode
	:type data: bytes
	:type str_encoding: string
	:rtype: None, list, object, string, dict
	"""
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
			if e is None:
				break
			out.append( e )
	elif t == "d": # dictionary
		out = { }
		while True:
			k = bdecode( data )
			if k is None:
				break
			out[k] = bdecode( data )
	elif t.isdigit( ): # string
		l = t
		c = chr( next( data ) )
		while c != ":":
			l += c
			c = chr( next( data ) )
		bout = bytearray( )
		for i in range( int( l ) ):
			bout.append( next( data ) )
		try:
			out = bout.decode( str_encoding )
		except UnicodeDecodeError:
			out = bout
	return out


def bencode( obj, str_encoding = "utf8" ):
	"""
	Encode object into binary string using bencode encoding.
	http://en.wikipedia.org/wiki/Bencode
	:type obj: object, int, dict, bytes
	:type str_encoding: string
	:rtype: bytes
	"""
	out = bytearray( )
	t = type( obj )
	if t == int:
		out.extend( "i{}e".format( obj ).encode( str_encoding ) )
	elif t == dict:
		out.extend( b"d" )
		for k in sorted( obj.keys( ) ):
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


def is_list_type( obj ):
	"""
	Returns true if object is traversable, but not a string or bytes.
	:type obj: object
	:rtype: bool
	"""
	return hasattr( obj, "__iter__" ) and not isinstance( obj, ( str, bytes ) )


def human_size( size, suffixes = ( "B", "kiB", "MiB", "GiB", "TiB" ), divisor = 1024. ):
	"""
	Returns byte size as human-readable string with size suffix.

	:type size: int
	:type suffixes: tuple
	:type divisor: float
	:rtype: str
	"""
	for s in suffixes:
		if size < divisor:
			if s == suffixes[0]:
				return "{}{}".format( round( size, 0 ), s )
			else:
				return "{:.2f}{}".format( round( size, 2 ), s )
		if s != suffixes[-1]:
			size /= float( divisor )
	return "{:.2f}{}".format( round( size, 2 ), suffixes[-1] )


def human_time_delta( seconds, max_elems = 2 ):
	"""
	Returns human readable description of the time span given in seconds.

	:type seconds: int
	:type max_elems: int
	:rtype: str
	"""
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


def _get_external_attrs( cls ):
	return [i for i in dir( cls ) if not re.search( "^_|_h$", i ) and not hasattr( getattr( cls, i ), "__call__" )]


def _url_quote( string ):
	"""
	:type string: string
	:rtype: string
	"""
	return urllib.parse.quote( string, "" )
