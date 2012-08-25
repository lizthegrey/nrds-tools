#!/usr/bin/python

from evelink import api, char, corp, eve
import ChatKosLookup
import sys

MAX_NPC_AGENT = 3020000

class StandingsChecker:
  def __init__(self, keyID, vCode, char_id):
    self.checker = ChatKosLookup.KosChecker()
    self.cache = self.checker.cache

    self.api = api.API(cache=self.cache, api_key=(keyID, vCode))
    self.corp = corp.Corp(api=self.api)
    self.eve = eve.EVE(api=self.api)
    self.char = char.Char(api=self.api, char_id=char_id)

  def check(self):
    contacts = self.char.contacts()

    for (key, value) in contacts.items():
      print key
      self.check_internal(value)

  def check_internal(self, contacts):
    entities = [(row['id'], row['name'], row['standing'])
                for row in contacts.values() if row['id'] > MAX_NPC_AGENT]

    alive_alliances = self.eve.alliances().keys()

    remove = {}
    demote = {}
    promote = {}
    for (eid, name, standing) in entities:
      kos = self.checker.koscheck_internal(name)
      if (not eid in alive_alliances and
          not self.valid_corp(eid) and not self.valid_char(eid)):
        remove[name] = standing
      elif standing < 0 and (kos == False or kos == ChatKosLookup.NPC):
        promote[name] = standing
      elif (standing >= 0 and
            kos != None and kos != ChatKosLookup.NPC and kos != False):
        demote[name] = standing
    if remove:
      print 'Defunct and can be removed:'
      for (name, standing) in sorted(remove.items()):
        print '%3d > [?]: %s' % (standing, name)
      print ''
    if demote:
      print 'KOS and should be < 0:'
      for (name, standing) in sorted(demote.items()):
        print '%3d > [-]: %s' % (standing, name)
      print ''
    if promote:
      print 'Not KOS and should be >=0 or removed:'
      for (name, standing) in sorted(promote.items()):
        print '%3d > [+]: %s' % (standing, name)
      print ''
    print '---'

  def valid_corp(self, eid):
    try:
      ret = self.corp.corporation_sheet(corp_id=eid)
      return (ret['ceo']['id'] != 0)
    except api.APIError:
      return False

  def valid_char(self, eid):
    try:
      self.eve.character_info_from_id(char_id=eid)
      return True
    except api.APIError:
      return False
    except ValueError:
      return False

if __name__ == '__main__':
  if len(sys.argv) > 3:
    StandingsChecker(sys.argv[1], sys.argv[2], sys.argv[3]).check()
  else:
    print ('Usage: %s keyID vCode' % sys.argv[0])

