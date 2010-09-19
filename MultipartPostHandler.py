#!/usr/bin/python

####
# 02/2006 Will Holcomb <wholcomb@gmail.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# 7/26/07 Slightly modified by Brian Schneider
# in order to support unicode files ( multipart_encode function )
# 19/09/10 Update to support Python 3.0 by Pavel Procopiuc
"""
Usage:
  Enables the use of multipart/form-data for posting forms

Inspirations:
  Upload files in python:
    http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/146306
  urllib2_file:
    Fabien Seisen: <fabien@seisen.org>

Example:
  import MultipartPostHandler, urllib2, cookielib

  cookies = cookielib.CookieJar()
  opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookies),
                                MultipartPostHandler.MultipartPostHandler)
  params = { "username" : "bob", "password" : "riviera",
             "file" : open("filename", "rb") }
  opener.open("http://wwww.bobsite.com/upload/", params)

Further Example:
  The main function of this file is a sample which downloads a page and
  then uploads it to the W3C validator.
"""

import urllib.request, urllib.parse
import email.generator, mimetypes
import os.path, io, sys

# Controls how sequences are uncoded. If true, elements may be given multiple values by
#  assigning a sequence.
doseq = 1

class MultipartPostHandler(urllib.request.BaseHandler):
    handler_order = urllib.request.HTTPHandler.handler_order - 10 # needs to run first

    def http_request(self, request):
        data = request.get_data()
        if data is not None and type(data) != str:
            v_files = []
            v_vars = []
            try:
                for(key, value) in data.items():
                    if isinstance(value, io.IOBase):
                        v_files.append((key, value))
                    else:
                        v_vars.append((key, value))
            except TypeError:
                raise TypeError( "not a valid non-string sequence or mapping object" )

            if len(v_files) == 0:
                data = urllib.parse.urlencode(v_vars, doseq)
            else:
                boundary, data = self.multipart_encode(v_vars, v_files)
                contenttype = 'multipart/form-data; boundary=' + boundary
                if(request.has_header('Content-Type')
                   and request.get_header('Content-Type').find('multipart/form-data') != 0):
                    print( "Replacing {0} with {1}".format(request.get_header('content-type'), 'multipart/form-data') )
                request.add_unredirected_header('Content-Type', contenttype)

            request.add_data(data)
        return request

    def multipart_encode(self, vars, files, boundary = None, buffer = None):
        if boundary is None:
            boundary = email.generator._make_boundary()
        if buffer is None:
            buffer = ''
        for(key, value) in vars:
            buffer += '--{0}\r\n'.format(boundary)
            buffer += 'Content-Disposition: form-data; name="{0}"'.format(key)
            buffer += '\r\n\r\n' + value + '\r\n'
        for(key, fd) in files:
            filename = os.path.basename(fd.name)
            contenttype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            buffer += '--{0}\r\n'.format(boundary)
            buffer += 'Content-Disposition: form-data; name="{0}"; filename="{1}"\r\n'.format(key, filename)
            buffer += 'Content-Type: {0}\r\n'.format(contenttype)
            fd.seek(0)
            buffer += '\r\n' + fd.read().decode( 'latin1' ) + '\r\n'
        buffer += '--{0}--\r\n\r\n'.format(boundary)
        return boundary, buffer

    https_request = http_request

def main():
    import tempfile

    validatorURL = "http://validator.w3.org/check"
    opener = urllib.request.build_opener(MultipartPostHandler)

    def validateFile(url):
        temp = tempfile.mkstemp(suffix=".html")
        os.write(temp[0], opener.open(url).read())
        params = { "ss" : "0",            # show source
                   "doctype" : "Inline",
                   "uploaded_file" : open(temp[1], "rb") }
        print(opener.open(validatorURL, params).read())
        os.remove(temp[1])

    if len(sys.argv[1:]) > 0:
        for arg in sys.argv[1:]:
            validateFile(arg)
    else:
        validateFile("http://www.google.com")

if __name__=="__main__":
    main()

