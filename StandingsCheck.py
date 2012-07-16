#!/usr/bin/python

from eveapi import eveapi
import ChatKosLookup
import sys

class StandingsChecker:
  def __init__(self, keyID, vCode):
    self.checker = ChatKosLookup.KosChecker()
    self.eveapi = self.checker.eveapi.auth(keyID=keyID, vCode=vCode)

  def check(self):
    contacts = self.eveapi.char.ContactList()

    print 'Personal'
    self.check_internal(contacts.contactList)
    print 'Corp'
    self.check_internal(contacts.corporateContactList)
    print 'Alliance'
    self.check_internal(contacts.allianceContactList)

  def check_internal(self, contacts):
    entities = [(row.contactID, row.contactName, row.standing)
                for row in contacts if row.contactID > 3100000]

    alive_alliances = [row.allianceID for row in
        self.checker.eveapi.eve.AllianceList(version=1).alliances]

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
      ret = self.checker.eveapi.corp.CorporationSheet(corporationID=eid)
      return (ret.ceoID != 0)
    except eveapi.Error:
      return False

  def valid_char(self, eid):
    try:
      self.checker.eveapi.eve.CharacterInfo(characterID=eid)
      return True
    except eveapi.Error:
      return False    

if __name__ == '__main__':
  if len(sys.argv) > 2:
    StandingsChecker(sys.argv[1], sys.argv[2]).check()
  else:
    print ('Usage: %s keyID vCode' % sys.argv[0])

