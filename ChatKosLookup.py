#!/usr/bin/env python

from eveapi import eveapi
import re, string, sys, os, tempfile, time, json, urllib2, zlib, cPickle

KOS_CHECKER_URL = 'http://kos.cva-eve.org/api/?c=json&type=unit&details&icon=64&max=10&offset=0&q=%s'
NPC = 'npc'

class SimpleCache(object):
  def __init__(self, debug=False):
    self.debug = debug
    self.count = 0
    self.cache = {}
    self.tempdir = os.path.join(tempfile.gettempdir(), 'eveapi')
    if not os.path.exists(self.tempdir):
      os.makedirs(self.tempdir)

  def log(self, what):
    if self.debug:
      print '[%d] %s' % (self.count, what)

  def retrieve(self, host, path, params):
    # eveapi asks if we have this request cached
    key = hash((host, path, frozenset(params.items())))

    self.count += 1  # for logging

    # see if we have the requested page cached...
    cached = self.cache.get(key, None)
    if cached:
      cacheFile = None
      #print "'%s': retrieving from memory" % path
    else:
      # it wasn't cached in memory, but it might be on disk.
      cacheFile = os.path.join(self.tempdir, str(key) + '.cache')
      if os.path.exists(cacheFile):
        self.log('%s: retrieving from disk at %s' % (path, cacheFile))
        f = open(cacheFile, 'rb')
        cached = self.cache[key] = cPickle.loads(zlib.decompress(f.read()))
        f.close()

    if cached:
      # check if the cached doc is fresh enough
      if time.time() < cached[0]:
        self.log('%s: returning cached document' % path)
        return cached[1]  # return the cached XML doc

      # it's stale. purge it.
      self.log('%s: cache expired, purging!' % path)
      del self.cache[key]
      if cacheFile:
        os.remove(cacheFile)

    self.log('%s: not cached, fetching from server...' % path)
    # we didn't get a cache hit so return None to indicate that the data
    # should be requested from the server.
    return None

  def store(self, host, path, params, doc, obj):
    # eveapi is asking us to cache an item
    key = hash((host, path, frozenset(params.items())))

    cachedFor = obj.cachedUntil - obj.currentTime
    if cachedFor:
      self.log('%s: cached (%d seconds)' % (path, cachedFor))

      cachedUntil = time.time() + cachedFor

      # store in memory
      cached = self.cache[key] = (cachedUntil, doc)

      # store in cache folder
      cacheFile = os.path.join(self.tempdir, str(key) + '.cache')
      f = open(cacheFile, 'wb')
      f.write(zlib.compress(cPickle.dumps(cached, -1)))
      f.close()

class CacheObject:
  def __init__(self):
    pass

class KosChecker:
  def __init__(self):
    self.cache = SimpleCache()
    self.eveapi = eveapi.EVEAPIConnection(cacheHandler=self.cache)

  def koscheck(self, player):
    kos = self.koscheck_internal(player)
    if kos == None or kos == NPC:
      # We were unable to find the player. Use employment history to
      # get their current corp and look that up. If it's an NPC corp,
      # we'll get bounced again.
      history = self.employment_history(player)

      if kos == None:
        kos = self.koscheck_internal(history[0])

      n = 1
      while kos == NPC and n < len(history):
        kos = self.koscheck_internal(history[n])
        n = n + 1

    if kos == None or kos == NPC:
      kos = False
    
    return kos

  def koscheck_internal(self, entity):
    result = self.cache.retrieve(KOS_CHECKER_URL, KOS_CHECKER_URL,
                                 {'entity': entity})
    if not result:
      result = json.load(urllib2.urlopen(KOS_CHECKER_URL % entity))
      obj = CacheObject()
      obj.cachedUntil = 60*60
      obj.currentTime = 0
      self.cache.store(KOS_CHECKER_URL, KOS_CHECKER_URL,
                       {'entity': entity}, result, obj)

    kos = None
    for value in result['results']:
      # Require exact match
      if value['label'] != entity:
        continue
      kos = value['kos']
      while value['type'] != 'alliance':
        kos |= value['kos']
        if 'npc' in value and value['npc'] and not kos:
          # Signal that further lookup is needed of player's last corp
          return NPC
        if 'corp' in value:
          value = value['corp']
        elif 'alliance' in value:
          value = value['alliance']
      break
    return kos

  def employment_history(self, character):
    cid = self.eveapi.eve.CharacterID(
        names=character).characters[0].characterID
    cdata = self.eveapi.eve.CharacterInfo(characterID=cid)
    corps = [row.corporationID for row in cdata.employmentHistory]
    uniqueCorps = []
    for value in corps:
      if value not in uniqueCorps:
        uniqueCorps.append(value)
    return [row.name for row in
                self.eveapi.eve.CharacterName(
                    ids=','.join(str(x) for x in uniqueCorps)).characters]

  def tail_file(self, filename):
    file = open(filename)
    while True:
      where = file.tell()
      line = file.readline()
      if not line:
        time.sleep(1)
        file.seek(where)
      else:
        sanitized = filter(lambda x:
                             x in string.printable and
                             x not in ['\n', '\r'],
                           line)
        if not 'xxx ' in sanitized:
          continue
        yield sanitized.split('xxx ')[1].split('  ')

  def loop(self, filename):
    for entry in self.tail_file(filename):
      kos = []
      notkos = []
      for person in entry:
        if self.koscheck(person):
          kos.append(person)
        else:
          notkos.append(person)

      
      format = '%s%6s (%3d) %s\033[0m'
      print format % ('\033[31m', 'KOS', len(kos), len(kos) * '*')
      print format % ('\033[34m', 'NotKOS', len(notkos), len(notkos) * '*')
      print
      for person in kos:
        print '\033[31m%s\033[0m' % person
      print
      for person in notkos:
        print '\033[34m%s\033[0m' % person
      print '\n-----\n'

if __name__ == '__main__':
  checker = KosChecker()
  if len(sys.argv) > 1:
    checker.loop(sys.argv[1])
  else:
    print 'Usage: %s ~/EVE/logs/ChatLogs/Fleet_YYYYMMDD_HHMMSS.txt' % sys.argv[0]
