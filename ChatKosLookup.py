#!/usr/bin/env python

"""Checks pilots mentioned in the EVE chatlogs against a KOS list."""

from eveapi import eveapi
import sys, string, os, tempfile, time, json, urllib2, zlib, cPickle, urllib

KOS_CHECKER_URL = 'http://kos.cva-eve.org/api/?c=json&type=unit&%s'
NPC = 'npc'
LASTCORP = 'lastcorp'

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

class FileTailer:
  def __init__(self, filename):
    self.handle = open(filename, 'rb')
    self.where = 0

  def poll(self):
    self.where = self.handle.tell()
    line = self.handle.readline()
    if not line:
      self.handle.seek(self.where)
      return (None, None)
    else:
      sanitized = ''.join([x for x in line if x in string.printable and
                                              x not in ['\n', '\r']])
      if not '> xxx ' in sanitized:
        return (None, None)
      person, command = sanitized.split('> xxx ', 1)
      person = person.split(']')[1].strip()
      mashup = command.split('#', 1)
      names = mashup[0]
      comment = '%s >' % person
      if len(mashup) > 1:
        comment = '%s > %s' % (person, mashup[1].strip())
      return (names.split('  '), comment)

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

      kos = self.koscheck_internal(history[0])
      in_npc_corp = (kos == NPC)

      idx = 0
      while kos == NPC and (idx + 1) < len(history):
        idx = idx + 1
        kos = self.koscheck_internal(history[idx])

      if in_npc_corp and kos != None and kos != NPC and kos != False:
        kos = '%s: %s' % (LASTCORP, history[idx])

    if kos == None or kos == NPC:
      kos = False

    return kos

  def koscheck_internal(self, entity):
    """Looks up KOS entries by directly calling the CVA KOS API."""
    result = self.cache.retrieve(KOS_CHECKER_URL, KOS_CHECKER_URL,
                                 {'entity': entity})
    if not result:
      result = json.load(urllib2.urlopen(
          KOS_CHECKER_URL % urllib.urlencode({'q' : entity})))
      obj = CacheObject(60*60)
      self.cache.store(KOS_CHECKER_URL, KOS_CHECKER_URL,
                       {'entity': entity}, result, obj)

    kos = None
    for value in result['results']:
      # Require exact match (case-insensitively).
      if value['label'].lower() != entity.lower():
        continue
      kos = False
      while True:
        if value['kos']:
          kos = '%s: %s' % (value['type'], value['label'])
        if 'npc' in value and value['npc'] and not kos:
          # Signal that further lookup is needed of player's last corp
          return NPC
        if 'corp' in value:
          value = value['corp']
        elif 'alliance' in value:
          value = value['alliance']
        else:
          return kos
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

  def loop(self, filename, handler):
    """Performs KOS processing on each line read from the log file.
    
    handler is a function of 3 args: (kos, notkos, error) that is called 
    every time there is a new KOS result.
    """
    tailer = FileTailer(filename)
    while True:
      entry, comment = tailer.poll()
      if not entry:
        time.sleep(1.0)
        continue
      kos, not_kos, error = self.koscheck_logentry(entry)
      handler(comment, kos, not_kos, error)

  def koscheck_logentry(self, entry):
    kos = []
    notkos = []
    error = []
    for person in entry:
      if person.isspace() or len(person) == 0:
        continue
      person = person.strip(' .')
      try:
        result = self.koscheck(person)
        if result != False:
          kos.append((person, result))
        else:
          notkos.append(person)
      except:
        error.append(person)
    return (kos, notkos, error)


def stdout_handler(comment, kos, notkos, error):
  fmt = '%s%6s (%3d) %s\033[0m'
  if comment:
    print comment
  print fmt % ('\033[31m', 'KOS', len(kos), len(kos) * '*')
  print fmt % ('\033[34m', 'NotKOS', len(notkos), len(notkos) * '*')
  if len(error) > 0:
    print fmt % ('\033[33m', 'Error', len(error), len(error) * '*')
  print
  for (person, reason) in kos:
    print u'\033[31m[\u2212] %s\033[0m (%s)' % (person, reason)
  print
  for person in notkos:
    print '\033[34m[+] %s\033[0m' % person
  print
  for person in error:
    print '\033[33m[?] %s\033[0m' % person
  print '-----'


if __name__ == '__main__':
  if len(sys.argv) > 1:
    KosChecker().loop(sys.argv[1], stdout_handler)
  else:
    print ('Usage: %s ~/EVE/logs/ChatLogs/Fleet_YYYYMMDD_HHMMSS.txt' %
           sys.argv[0])

