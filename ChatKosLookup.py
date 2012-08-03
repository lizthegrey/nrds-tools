#!/usr/bin/env python

"""Checks pilots mentioned in the EVE chatlogs against a KOS list."""

from evelink import api, eve
from evelink.cache import shelf
import sys, string, os, tempfile, time, json, urllib2, urllib

KOS_CHECKER_URL = 'http://kos.cva-eve.org/api/?c=json&type=unit&%s'
NPC = 'npc'
LASTCORP = 'lastcorp'

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
      left, command = sanitized.split('> xxx ', 1)
      timestamp = left.split(']', 1)[0].split(' ')[2]
      person = left.split(']', 1)[1].strip()
      mashup = command.split('#', 1)
      names = mashup[0]
      comment = '[%s] %s >' % (timestamp, person)
      if len(mashup) > 1:
        comment = '[%s] %s > %s' % (timestamp, person, mashup[1].strip())
      return (names.split('  '), comment)

class KosChecker:
  """Maintains API state and performs KOS checks."""

  def __init__(self):
    # Set up caching.
    cache_file = os.path.join(tempfile.gettempdir(), 'koscheck')
    self.cache = shelf.ShelveCache(cache_file)

    self.api = api.API(cache=self.cache)
    self.eve = eve.EVE(api=self.api)

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
    cache_key = self.api._cache_key(KOS_CHECKER_URL, {'entity': entity})

    result = self.cache.get(cache_key)
    if not result:
      result = json.load(urllib2.urlopen(
          KOS_CHECKER_URL % urllib.urlencode({'q' : entity})))
      self.cache.put(cache_key, result, 60*60)

    kos = None
    for value in result['results']:
      # Require exact match (case-insensitively).
      if value['label'].lower() != entity.lower():
        continue
      if value['type'] == 'alliance' and value['ticker'] == None:
        # Bogus alliance created instead of NPC corp.
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
    cid = self.eve.character_id_from_name(character)
    cdata = self.eve.character_info_from_id(cid)
    corps = cdata['history']
    unique_corps = []
    for corp in corps:
      if corp['corp_id'] not in unique_corps:
        unique_corps.append(corp['corp_id'])
    mapping = self.eve.character_names_from_ids(unique_corps)
    return [mapping[cid] for cid in unique_corps]

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

