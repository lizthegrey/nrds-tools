import ctypes
import ctypes.wintypes
import datetime
import os

import wx

import ChatKosLookup


DIVIDER = '-' * 40


# Cargo-culted from:
# http://stackoverflow.com/questions/3927259/how-do-you-get-the-exact-path-to-my-documents
def GetMyDocumentsDir():
  shell32 = ctypes.windll.shell32
  buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH + 1)
  if shell32.SHGetSpecialFolderPathW(None, buf, 0x5, False):
    return buf.value
  return None


def GetEveLogsDir():
  home = GetMyDocumentsDir()
  if not home:
    return None
  if os.path.isdir(os.path.join(home, 'EVE', 'logs', 'Chatlogs')):
    return os.path.join(home, 'EVE', 'logs', 'Chatlogs')
  if os.path.isdir(os.path.join(home, 'CCP', 'EVE', 'logs', 'Chatlogs')):
    return os.path.join(home, 'CCP', 'EVE', 'logs', 'Chatlogs')
  return None


class MainFrame(wx.Frame):
  def __init__(self, *args, **kwargs):
    wx.Frame.__init__(self, *args, **kwargs)
    self.working_file = self.GetWorkingFile()
    if not self.working_file:
      self.Close()
      return
    self.checker = ChatKosLookup.KosChecker()
    self.tailer = ChatKosLookup.FileTailer(self.working_file)
    self.labels = []
    self.text_boxes = []
    for i in xrange(100):
      text = wx.StaticText(self, -1, '', (5, 16 * i + 5))
      self.text_boxes.append(text)
    self.SetSize((150, 800))
    self.SetBackgroundColour('white')
    self.Show()
    self.KosCheckerPoll()

  def KosCheckerPoll(self):
    entry = self.tailer.poll()
    if not entry:
      wx.FutureCall(1000, self.KosCheckerPoll)
      return
    kos, not_kos, error = self.checker.koscheck_entry(entry)
    new_labels = []
    if kos or not_kos:
      new_labels.append('KOS: %d  Not KOS: %d' % (len(kos), len(not_kos)))
    if kos:
      # Unicode MINUS SIGN
      new_labels.extend([u'[\u2212] %s' % p for p in kos])
    if not_kos:
      if kos:
        new_labels.append(' ')
      new_labels.extend(['[+] %s' % p for p in not_kos])
    if error:
      new_labels.append('Error: %d' % len(error))
      new_labels.extend(error)
    if new_labels:
      new_labels.append(DIVIDER)
    self.labels = new_labels + self.labels
    self.labels = self.labels[:100]
    self.UpdateLabels()
    wx.FutureCall(100, self.KosCheckerPoll)

  def UpdateLabels(self):
    current_color = None
    for i, label in enumerate(self.labels):
      if label.startswith('[+]'):
        current_color = 'blue'
      elif label.startswith(u'[\u2212]'):
        current_color = 'red'
      else:
	current_color = 'black'
      self.text_boxes[i].SetForegroundColour(current_color)
      self.text_boxes[i].SetLabel(label)

  def GetWorkingFile(self):
    today = datetime.date.today().strftime('%Y%m%d')
    wildcards = [
        'Fleet logs (today)', 'Fleet_%s_*.txt' % today,
	'Fleet logs (all)', 'Fleet*.txt',
	'All logs (today)', '*_%s_*.txt' % today,
	'All logs', '*.txt']
    dialog = wx.FileDialog(
        self,
        'Choose a log file',
        GetEveLogsDir(),
        style=wx.OPEN,
        wildcard='|'.join(wildcards))
    result = dialog.ShowModal()
    if result != wx.ID_OK:
      return None
    return dialog.GetPath()


if __name__ == '__main__':
  app = wx.App()
  frame = MainFrame(None, -1, 'KOS Checker')
  app.MainLoop()

