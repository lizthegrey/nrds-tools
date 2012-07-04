#!/usr/bin/env python

"""Checks pilots mentioned in the EVE chatlogs against a KOS list."""

from eveapi import eveapi
import sys, string, os, tempfile, time, json, urllib2, zlib, cPickle

KOS_CHECKER_URL = 'http://kos.cva-eve.org/api/?c=json&' \
                  'type=unit&details&icon=64&max=10&offset=0&q=%s'
NPC = 'npc'

class SimpleCache(object):
  """Implements a memory and disk-based cache of previous API calls."""

  def __init__(self, debug=False):
    self.debug = debug
    self.count = 0
    self.cache = {}
    self.tempdir = os.path.join(tempfile.gettempdir(), 'eveapi')
    if not os.path.exists(self.tempdir):
      os.makedirs(self.tempdir)

  def log(self, what):
    """Outputs debug information if the debug flag is set."""
    if self.debug:
      print '[%d] %s' % (self.count, what)

  def retrieve(self, host, path, params):
    """Retrieves a cached value, or returns None if not cached."""
    # eveapi asks if we have this request cached
    key = hash((host, path, frozenset(params.items())))

    self.count += 1  # for logging

    # see if we have the requested page cached...
    cached = self.cache.get(key, None)
    if cached:
      cache_file = None
      #print "'%s': retrieving from memory" % path
    else:
      # it wasn't cached in memory, but it might be on disk.
      cache_file = os.path.join(self.tempdir, str(key) + '.cache')
      if os.path.exists(cache_file):
        self.log('%s: retrieving from disk at %s' % (path, cache_file))
        handle = open(cache_file, 'rb')
        cached = self.cache[key] = cPickle.loads(
            zlib.decompress(handle.read()))
        handle.close()

    if cached:
      # check if the cached doc is fresh enough
      if time.time() < cached[0]:
        self.log('%s: returning cached document' % path)
        return cached[1]  # return the cached XML doc

      # it's stale. purge it.
      self.log('%s: cache expired, purging!' % path)
      del self.cache[key]
      if cache_file:
        os.remove(cache_file)

    self.log('%s: not cached, fetching from server...' % path)
    # we didn't get a cache hit so return None to indicate that the data
    # should be requested from the server.
    return None

  def store(self, host, path, params, doc, obj):
    """Saves a cached value to the backing stores."""
    # eveapi is asking us to cache an item
    key = hash((host, path, frozenset(params.items())))

    cached_for = obj.cachedUntil - obj.currentTime
    if cached_for:
      self.log('%s: cached (%d seconds)' % (path, cached_for))

      cached_until = time.time() + cached_for

      # store in memory
      cached = self.cache[key] = (cached_until, doc)

      # store in cache folder
      cache_file = os.path.join(self.tempdir, str(key) + '.cache')
      handle = open(cache_file, 'wb')
      handle.write(zlib.compress(cPickle.dumps(cached, -1)))
      handle.close()

class CacheObject:
  """Allows caching objects that do not come from the EVE api."""
  def __init__(self, valid_duration_seconds):
    self.cachedUntil = valid_duration_seconds
    self.currentTime = 0

def tail_file(filename):
  """Repeatedly reads the end of a chat log and filters for names."""
  handle = open(filename)
  while True:
    where = handle.tell()
    line = handle.readline()
    if not line:
      time.sleep(1)
      handle.seek(where)
    else:
      sanitized = ''.join([x for x in line if x in string.printable and
                                              x not in ['\n', '\r']])
      if not '> xxx ' in sanitized:
        continue
      yield sanitized.split('> xxx ')[1].split('  ')

class KosChecker:
  """Maintains API state and performs KOS checks."""

  def __init__(self):
    self.cache = SimpleCache()
    self.eveapi = eveapi.EVEAPIConnection(cacheHandler=self.cache)

  def koscheck(self, player):
    """Checks a given player against the KOS list, including esoteric rules."""
    kos = self.koscheck_internal(player)
    if kos == None or kos == NPC:
      # We were unable to find the player. Use employment history to
      # get their current corp and look that up. If it's an NPC corp,
      # we'll get bounced again.
      history = self.employment_history(player)

      if kos == None:
        kos = self.koscheck_internal(history[0])

      idx = 1
      while kos == NPC and idx < len(history):
        kos = self.koscheck_internal(history[idx])
        idx = idx + 1

    if kos == None or kos == NPC:
      kos = False
    
    return kos

  def koscheck_internal(self, entity):
    """Looks up KOS entries by directly calling the CVA KOS API."""
    result = self.cache.retrieve(KOS_CHECKER_URL, KOS_CHECKER_URL,
                                 {'entity': entity})
    if not result:
      result = json.load(urllib2.urlopen(KOS_CHECKER_URL % entity))
      obj = CacheObject(60*60)
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
    """Retrieves a player's most recent corporations via EVE api."""
    cid = self.eveapi.eve.CharacterID(
        names=character).characters[0].characterID
    cdata = self.eveapi.eve.CharacterInfo(characterID=cid)
    corps = [row.corporationID for row in cdata.employmentHistory]
    unique_corps = []
    for value in corps:
      if value not in unique_corps:
        unique_corps.append(value)
    return [row.name for row in
                self.eveapi.eve.CharacterName(
                    ids=','.join(str(x) for x in unique_corps)).characters]

  def loop(self, filename):
    """Performs KOS processing on each line read from the log file."""
    for entry in tail_file(filename):
      kos = []
      notkos = []
      for person in entry:
        if self.koscheck(person):
          kos.append(person)
        else:
          notkos.append(person)

      
      fmt = '%s%6s (%3d) %s\033[0m'
      print fmt % ('\033[31m', 'KOS', len(kos), len(kos) * '*')
      print fmt % ('\033[34m', 'NotKOS', len(notkos), len(notkos) * '*')
      print
      for person in kos:
        print '\033[31m%s\033[0m' % person
      print
      for person in notkos:
        print '\033[34m%s\033[0m' % person
      print '\n-----\n'

if __name__ == '__main__':
  if len(sys.argv) > 1:
    KosChecker().loop(sys.argv[1])
  else:
    print ('Usage: %s ~/EVE/logs/ChatLogs/Fleet_YYYYMMDD_HHMMSS.txt' %
           sys.argv[0])

