"""
Priority
"""

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
