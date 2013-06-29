#!/usr/bin/env python

# This little script allows the importation of sample data from 
# the CMS Data Aggregation System (DAS).
# It is derived from the DAS CLI code that can be downloaded at
# https://cmsweb.cern.ch/das/cli

import sys
if  sys.version_info < (2, 6):
    raise Exception("DAS requires python 2.6 or greater")

import os
import re
import time
import json
import urllib
import urllib2
import httplib
import string
import pprint
from optparse import OptionParser
from datetime import datetime
from SAMADhi import Dataset, DbStore

class HTTPSClientAuthHandler(urllib2.HTTPSHandler):
    """
    Simple HTTPS client authentication class based on provided
    key/ca information
    """
    def __init__(self, key=None, cert=None, level=0):
        if  level:
            urllib2.HTTPSHandler.__init__(self, debuglevel=1)
        else:
            urllib2.HTTPSHandler.__init__(self)
        self.key = key
        self.cert = cert

    def https_open(self, req):
        """Open request method"""
        #Rather than pass in a reference to a connection class, we pass in
        # a reference to a function which, for all intents and purposes,
        # will behave as a constructor
        return self.do_open(self.get_connection, req)

    def get_connection(self, host, timeout=300):
        """Connection method"""
        if  self.key:
            return httplib.HTTPSConnection(host, key_file=self.key,
                                                cert_file=self.cert)
        return httplib.HTTPSConnection(host)

class DASOptionParser: 
    """
    DAS cache client option parser
    """
    def __init__(self):
        usage  = "Usage: %prog [options]\n"
        self.parser = OptionParser(usage=usage)
        self.parser.add_option("-v", "--verbose", action="store", 
                               type="int", default=0, dest="verbose",
             help="verbose output")
        self.parser.add_option("--sample", action="store", type="string", 
                               default=False, dest="sample",
             help="specify sample for your request.")
        self.parser.add_option("--process", action="store", type="string",
                               default=None, dest="process",
             help="specify process name. TLatex synthax may be used.")
        self.parser.add_option("--xsection", action="store", type="float",
                               default=0.0, dest="xsection",
             help="specify the cross-section.")
        self.parser.add_option("--energy", action="store", type="float",
                               default=0.0, dest="energy",
             help="specify the centre of mass energy.")
        self.parser.add_option("--comment", action="store", type="string",
                               default="", dest="comment",
             help="comment about the dataset")
        msg  = "host name of DAS cache server, default is https://cmsweb.cern.ch"
        self.parser.add_option("--host", action="store", type="string", 
                       default='https://cmsweb.cern.ch', dest="host", help=msg)
        msg  = "index for returned result"
        self.parser.add_option("--idx", action="store", type="int", 
                               default=0, dest="idx", help=msg)
        msg  = 'query waiting threshold in sec, default is 5 minutes'
        self.parser.add_option("--threshold", action="store", type="int",
                               default=300, dest="threshold", help=msg)
        msg  = 'specify private key file name'
        self.parser.add_option("--key", action="store", type="string",
                               default="", dest="ckey", help=msg)
        msg  = 'specify private certificate file name'
        self.parser.add_option("--cert", action="store", type="string",
                               default="", dest="cert", help=msg)
        msg = 'specify number of retries upon busy DAS server message'
        self.parser.add_option("--retry", action="store", type="string",
                               default=0, dest="retry", help=msg)
        msg = 'drop DAS headers'
        self.parser.add_option("--das-headers", action="store_true",
                               default=False, dest="das_headers", help=msg)
    def get_opt(self):
        """
        Returns parse list of options
        """
        return self.parser.parse_args()

def fullpath(path):
    "Expand path to full path"
    if  path and path[0] == '~':
        path = path.replace('~', '')
        path = path[1:] if path[0] == '/' else path
        path = os.path.join(os.environ['HOME'], path)
    return path

def get_data(host, query, idx, limit, debug, threshold=300, ckey=None,
        cert=None, das_headers=True):
    """Contact DAS server and retrieve data for given DAS query"""
    params  = {'input':query, 'idx':idx, 'limit':limit}
    path    = '/das/cache'
    pat     = re.compile('http[s]{0,1}://')
    if  not pat.match(host):
        msg = 'Invalid hostname: %s' % host
        raise Exception(msg)
    url = host + path
    headers = {"Accept": "application/json"}
    encoded_data = urllib.urlencode(params, doseq=True)
    url += '?%s' % encoded_data
    req  = urllib2.Request(url=url, headers=headers)
    if  ckey and cert:
        ckey = fullpath(ckey)
        cert = fullpath(cert)
        hdlr = HTTPSClientAuthHandler(ckey, cert, debug)
    else:
        hdlr = urllib2.HTTPHandler(debuglevel=debug)
    opener = urllib2.build_opener(hdlr)
    fdesc = opener.open(req)
    data = fdesc.read()
    fdesc.close()

    pat = re.compile(r'^[a-z0-9]{32}')
    if  data and isinstance(data, str) and pat.match(data) and len(data) == 32:
        pid = data
    else:
        pid = None
    iwtime  = 2  # initial waiting time in seconds
    wtime   = 20 # final waiting time in seconds
    sleep   = iwtime
    time0   = time.time()
    while pid:
        params.update({'pid':data})
        encoded_data = urllib.urlencode(params, doseq=True)
        url  = host + path + '?%s' % encoded_data
        req  = urllib2.Request(url=url, headers=headers)
        try:
            fdesc = opener.open(req)
            data = fdesc.read()
            fdesc.close()
        except urllib2.HTTPError as err:
            return {"status":"fail", "reason":str(err)}
        if  data and isinstance(data, str) and pat.match(data) and len(data) == 32:
            pid = data
        else:
            pid = None
        time.sleep(sleep)
        if  sleep < wtime:
            sleep *= 2
        elif sleep == wtime:
            sleep = iwtime # start new cycle
        else:
            sleep = wtime
        if  (time.time()-time0) > threshold:
            reason = "client timeout after %s sec" % int(time.time()-time0)
            return {"status":"fail", "reason":reason}
    jsondict = json.loads(data)
    if  das_headers:
        return jsondict
    # drop DAS headers, users usually don't need them
    status = jsondict.get('status')
    if  status != 'ok':
        return jsondict
    drop_keys = ['das_id', 'cache_id', 'qhash', '_id', 'das']
    for row in jsondict['data']:
        for key in drop_keys:
            del row[key]
    return jsondict['data']

def asDataset(dct):
  """Convert json into a Dataset"""
  # definition of the conversion key -> column
  conversion = { "process":u'process', 
                 "user_comment":u'comment',
                 "energy":u'energy',
                 "nevents":u'nevents',
                 "cmssw_release":u'release',
                 "dsize":u'size',
                 "globaltag":u'tag',
                 "xsection":u'xsection' }
  # create the Dataset
  result = Dataset(dct["name"], dct["datatype"])
  for column,key in conversion.iteritems():
    setattr(result,column,dct[key])
  # special cases
  result.creation_time = datetime.strptime(dct[u'creation_time'],"%Y-%m-%d %H:%M:%S")
  return result

def asDict(dataset):
  """Convert a Dataset to json"""
  # definition of the conversion key -> column
  conversion = { "name":u'name',
                 "datatype":u'datatype',
                 "process":u'process', 
                 "user_comment":u'comment',
                 "energy":u'energy',
                 "nevents":u'nevents',
                 "cmssw_release":u'release',
                 "dsize":u'size',
                 "globaltag":u'tag',
                 "xsection":u'xsection' }
  # create the dict
  result = {}
  for column,key in conversion.iteritems():
    result[key] = getattr(dataset,column)
  # special cases
  result[u'creation_time'] = dataset.creation_time.strftime("%Y-%m-%d %H:%M:%S")
  return result
  
def confirm(prompt=None, resp=False):
    """prompts for yes or no response from the user. Returns True for yes and
    False for no. 'resp' should be set to the default value assumed by the caller when
    user simply types ENTER.
    >>> confirm(prompt='Create Directory?', resp=True)
    Create Directory? [y]|n: 
    True
    >>> confirm(prompt='Create Directory?', resp=False)
    Create Directory? [n]|y: 
    False
    >>> confirm(prompt='Create Directory?', resp=False)
    Create Directory? [n]|y: y
    True
    """
    if prompt is None:
        prompt = 'Confirm'
    if resp:
        prompt = '%s [%s]|%s: ' % (prompt, 'y', 'n')
    else:
        prompt = '%s [%s]|%s: ' % (prompt, 'n', 'y')
    while True:
        ans = raw_input(prompt)
        if not ans:
            return resp
        if ans not in ['y', 'Y', 'n', 'N']:
            print 'please enter y or n.'
            continue
        if ans == 'y' or ans == 'Y':
            return True
        if ans == 'n' or ans == 'N':
            return False

def main():
    """Main function"""
    # get the options
    optmgr  = DASOptionParser()
    opts, _ = optmgr.get_opt()
    host    = opts.host
    debug   = opts.verbose
    sample  = opts.sample
    query1 = "dataset="+sample+" | grep dataset.name, dataset.nevents, dataset.size, dataset.tag, dataset.datatype, dataset.creation_time"
    query2 = "release dataset="+sample+" | grep release.name"
    idx     = opts.idx
    thr     = opts.threshold
    ckey    = opts.ckey
    cert    = opts.cert
    das_h   = opts.das_headers
    # perform the DAS queries
    jsondict1 = get_data(host, query1, idx, 1, debug, thr, ckey, cert, das_h)
    jsondict2 = get_data(host, query2, idx, 1, debug, thr, ckey, cert, das_h)
    # check the result
    if not(isinstance(jsondict1, list) and 
           len(jsondict1)==1 and 
           isinstance(jsondict1[0], dict) and
           isinstance(jsondict1[0]["dataset"],list) and
           len(jsondict1[0]["dataset"])==1 and
           isinstance(jsondict1[0]["dataset"][0],dict) and
           isinstance(jsondict2, list) and
           len(jsondict2)==1 and
           isinstance(jsondict2[0], dict) and
           isinstance(jsondict2[0]["release"],list) and
           len(jsondict2[0]["release"])==1 and
           isinstance(jsondict2[0]["release"][0],dict)):
      raise RuntimeError("Incorrect response from DAS:\n"+str(jsondict1)+"\n"+str(jsondict2))
    # prepare the summary json object
    jsondict1[0]["dataset"][0][u"release"] = jsondict2[0]["release"][0]["name"]
    if opts.process is None:
      opts.process = string.split(jsondict1[0]["dataset"][0]["name"],'/',2)[1]
    jsondict1[0]["dataset"][0].update({ u"process":unicode(opts.process), 
                                        u"xsection":opts.xsection, u"energy":opts.energy, 
                                        u"comment":unicode(opts.comment) })
    # convert the jsondict into a Dataset
    dataset = asDataset(jsondict1[0]["dataset"][0])
    # connect to the MySQL database using default credentials
    dbstore = DbStore()
    # check that there is no existing entry
    checkExisting = dbstore.find(Dataset,Dataset.name==dataset.name)
    if checkExisting.is_empty():
      pp = pprint.PrettyPrinter()
      pp.pprint(jsondict1[0]["dataset"][0])
      if confirm(prompt="Insert into the database?", resp=True):
        dbstore.add(dataset)
    else:
      pp = pprint.PrettyPrinter()
      prompt  = "Replace existing entry:\n"
      prompt += pp.pformat(asDict(checkExisting.one()))
      prompt += "\nby new entry:\n"
      prompt += pp.pformat(jsondict1[0]["dataset"][0])
      prompt += "\n?"
      if confirm(prompt, resp=False):
        checkExisting.remove()
        dbstore.add(dataset)
    # commit
    dbstore.commit()

#
# main
#
if __name__ == '__main__':
    main()
