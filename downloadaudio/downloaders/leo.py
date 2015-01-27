# -*- mode: python; coding: utf-8 -*-
#
# Copyright © 2012–2013 Roland Sieker, ospalh@gmail.com
# Copyright © 2015 Paul Hartmann <phaaurlt@gmail.com>
#
# License: GNU AGPL, version 3 or later;
# http://www.gnu.org/copyleft/agpl.html


'''
Download pronunciations from leo.org
'''

from collections import OrderedDict
import re
import urllib
import xml.etree.ElementTree as ElementTree

# Make this work without PyQt
with_pyqt = True
try:
    from PyQt4.QtGui import QImage
except ImportError:
    with_pyqt = False

from .downloader import AudioDownloader
from ..download_entry import DownloadEntry


class LeoDownloader(AudioDownloader):
    """Download audio from LEO"""
    def __init__(self):
        AudioDownloader.__init__(self)
        self.file_extension = u'.mp3'
        self.dic_url = \
            'http://dict.leo.org/dictQuery/m-vocab/{lang}de/query.xml?' \
            'tolerMode=nof&lp={lang}de&lang=de&rmWords=off&rmSearch=on' \
            '&search={word}&searchLoc={direction}&resultOrder=basic' \
            '&multiwordShowSingle=on&sectLenMax=16'
        self.SEARCH_DIRECTION = { 'from_german': '1', 'to_german': '-1' }
        self.audio_url = 'http://dict.leo.org/media/audio/{id}.mp3'
        # And, yes, they use ch for Chinese.
        self.language_dict = {'de': 'de', 'en': 'en', 'fr': 'fr', 'es': 'es',
                              # at time of writing, leo.org has no audio for the
                              # following languages
                              #'it': 'it', 'zh': 'ch', 'ru': 'ru', 'pt': 'pt',
                              #'pl': 'pl'
                              }
        # We should keep a number of site icons handy, with the right
        # flag for the request.
        self.site_icon_dict = {}
        self.icon_url_dict = {
            'de': 'http://dict.leo.org/img/favicons/ende.ico',
            'en': 'http://dict.leo.org/img/favicons/ende.ico',
            'fr': 'http://dict.leo.org/img/favicons/frde.ico',
            'es': 'http://dict.leo.org/img/favicons/esde.ico',
            #'it': 'http://dict.leo.org/img/favicons/itde.ico',
            # # When we use this dict, we have already munged the 'zh' to 'ch'
            #'ch': 'http://dict.leo.org/img/favicons/chde.ico',
            #'ru': 'http://dict.leo.org/img/favicons/rude.ico',
            #'pt': 'http://dict.leo.org/img/favicons/ptde.ico',
            #'pl': 'http://dict.leo.org/img/favicons/plde.ico'
            }

    def download_files(self, word, base, ruby, split):
        """
        Download a word from LEO
        """
#        from aqt.qt import debug; debug()
        self.downloads_list = []
        if split:
            # Avoid double downloads
            return
        # Fix the language. EAFP.
        try:
            self.language = self.language_dict[self.language[:2].lower()]
        except KeyError:
            return

        self.get_flag_icon()

        # To find the audio links, look up dictionary entries, which are
        # en<->de, fr<->de, es<->de, etc.
        # For German entries, use de->en.
        if self.language == 'de':
            query_lang = 'en'
            direction = self.SEARCH_DIRECTION['from_german']
        else:
            query_lang = self.language
            direction = self.SEARCH_DIRECTION['to_german']

        xml = self.get_data_from_url(self.dic_url.format(lang=query_lang,
            word=urllib.quote_plus(word.encode('utf-8')), direction=direction))
        root = ElementTree.fromstring(xml)
        hits = OrderedDict()
        for section in root.findall('sectionlist/section'):
            for entry in section.findall('entry'):
                if self.language == 'de':
                     # Second side is always German.
                    side = entry.findall('side')[1]
                else:
                     # And the first side the other requested language.
                    side = entry.findall('side')[0]
                if side.attrib['lang'] != self.language: # consistency check
                    raise ValueError()

                matching_word = None
                for el_word in side.findall('words/word'):
                    cur_word = el_word.text
                    # Text in ElementTree has inconsistent types: "str" when it
                    # contains only ASCII characters and "unicode" otherwise.
                    # Make everything unicode.
                    if type(cur_word) == str:
                        cur_word = cur_word.decode('utf-8')
                    if self.normalize(cur_word) == self.normalize(word):
                        matching_word = cur_word
                        break
                if not matching_word:
                    continue
                pron = side.find('ibox/pron')
                if pron is None:
                    continue # no audio file for this entry
                audio_id = pron.attrib['url']
                hits[audio_id] = matching_word
        for audio_id, matching_word in hits.items():
            self.download_audio(audio_id, self.adjust_to_audio(matching_word))

    def download_audio(self, audio_id, word):
        """
        Download audio file with a given id from leo.org.
        """
        word_data = self.get_data_from_url(self.audio_url.format(id=audio_id))
        word_file_path, word_file_name = self.get_file_name(
            word, self.file_extension)
        with open(word_file_path, 'wb') as word_file:
            word_file.write(word_data)
        # We have a file, but not much to say about it.
        self.downloads_list.append(DownloadEntry(
            word_file_path, word_file_name, base_name=word, display_text=word,
            file_extension=self.file_extension, extras=dict(Source='Leo')))

    def get_flag_icon(self):
        """
        Set self.site_icon to the right icon.

        We should use different icons, depending on the request
        language.  We store these icons in self.site_icon_dict and use the
        AudioDownloader.maybe_get_icon() if we don't have it yet.
        """
        if not with_pyqt:
            return
        try:
            # If this works we already have it.
            self.site_icon = self.site_icon_dict[self.language]
        except KeyError:
            # We have to get it ourself. (We know it's just 16x16, so
            # no resize. And we know the address).
            self.site_icon_dict[self.language] = \
                QImage.fromData(self.get_data_from_url(
                    self.icon_url_dict[self.language]))
            self.site_icon = self.site_icon_dict[self.language]

    def normalize(self, word):
        """
        For comparison of two words / entries, strip articles, particles and
        similar words.

        Typically these additional words give extra information, but do not
        change the identity of the main phrase or word.
        Therefore they are removed before matching the user request with the
        dictionary entry.
        """
        if self.language == 'de':
            addenda = ['der', 'die', 'das']
        elif self.language == 'en':
            addenda = ['to', 'sth.', 'so.']
        elif self.language == 'fr':
            addenda = ['le', 'la', 'qn.', 'qc.']
        elif self.language == 'es':
            addenda = ['el', 'la']
        word = word.lower()
        for a in addenda:
            word = re.sub('^{} '.format(a), '', word)
            word = re.sub(',? {}$'.format(a), '', word)
        return word

    def adjust_to_audio(self, word):
        """
        Adjusts the dictionary text to what is actually spoken in the audio
        file.

        There are certain patterns, for example in Spanish, articles for nouns
        are included in the dictionary text, but not in the audio.
        Similarly, the verb-entries in English have a "to" in front, which is
        omitted in the audio.
        """
        if self.language == 'de':
            addenda = []
        elif self.language == 'en':
            addenda = ['to']
        elif self.language == 'fr':
            addenda = ['qn.', 'qc.']
        elif self.language == 'es':
            addenda = ['el', 'la']
        for a in addenda:
            word = re.sub('^{} '.format(a), '', word)
            word = re.sub(',? {}$'.format(a), '', word)
        return word

