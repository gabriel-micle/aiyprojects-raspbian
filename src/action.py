# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Carry out voice commands by recognising keywords."""

import datetime
import logging
import subprocess

import phue
from rgbxy import Converter

import json 
import pprint
import re
import RPi.GPIO as GPIO
import time
import urllib
import vlc
import youtube_dl

import actionbase

# =============================================================================
#
# Hey, Makers!
#
# This file contains some examples of voice commands that are handled locally,
# right on your Raspberry Pi.
#
# Do you want to add a new voice command? Check out the instructions at:
# https://aiyprojects.withgoogle.com/voice/#makers-guide-3-3--create-a-new-voice-command-or-action
# (MagPi readers - watch out! You should switch to the instructions in the link
#  above, since there's a mistake in the MagPi instructions.)
#
# In order to make a new voice command, you need to do two things. First, make a
# new action where it says:
#   "Implement your own actions here"
# Secondly, add your new voice command to the actor near the bottom of the file,
# where it says:
#   "Add your own voice commands here"
#
# =============================================================================

# Actions might not use the user's command. pylint: disable=unused-argument


# Example: Say a simple response
# ================================
#
# This example will respond to the user by saying something. You choose what it
# says when you add the command below - look for SpeakAction at the bottom of
# the file.
#
# There are two functions:
# __init__ is called when the voice commands are configured, and stores
# information about how the action should work:
#   - self.say is a function that says some text aloud.
#   - self.words are the words to use as the response.
# run is called when the voice command is used. It gets the user's exact voice
# command as a parameter.

class SpeakAction(object):

    """Says the given text via TTS."""

    def __init__(self, say, words):
        self.say = say
        self.words = words

    def run(self, voice_command):
        self.say(self.words)


# Example: Tell the current time
# ==============================
#
# This example will tell the time aloud. The to_str function will turn the time
# into helpful text (for example, "It is twenty past four."). The run function
# uses to_str say it aloud.

class SpeakTime(object):

    """Says the current local time with TTS."""

    def __init__(self, say):
        self.say = say

    def run(self, voice_command):
        time_str = self.to_str(datetime.datetime.now())
        self.say(time_str)

    def to_str(self, dt):
        """Convert a datetime to a human-readable string."""
        HRS_TEXT = ['midnight', 'one', 'two', 'three', 'four', 'five', 'six',
                    'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve']
        MINS_TEXT = ["five", "ten", "quarter", "twenty", "twenty-five", "half"]
        hour = dt.hour
        minute = dt.minute

        # convert to units of five minutes to the nearest hour
        minute_rounded = (minute + 2) // 5
        minute_is_inverted = minute_rounded > 6
        if minute_is_inverted:
            minute_rounded = 12 - minute_rounded
            hour = (hour + 1) % 24

        # convert time from 24-hour to 12-hour
        if hour > 12:
            hour -= 12

        if minute_rounded == 0:
            if hour == 0:
                return 'It is midnight.'
            return "It is %s o'clock." % HRS_TEXT[hour]

        if minute_is_inverted:
            return 'It is %s to %s.' % (MINS_TEXT[minute_rounded - 1], HRS_TEXT[hour])
        return 'It is %s past %s.' % (MINS_TEXT[minute_rounded - 1], HRS_TEXT[hour])


# Example: Run a shell command and say its output
# ===============================================
#
# This example will use a shell command to work out what to say. You choose the
# shell command when you add the voice command below - look for the example
# below where it says the IP address of the Raspberry Pi.

class SpeakShellCommandOutput(object):

    """Speaks out the output of a shell command."""

    def __init__(self, say, shell_command, failure_text):
        self.say = say
        self.shell_command = shell_command
        self.failure_text = failure_text

    def run(self, voice_command):
        output = subprocess.check_output(self.shell_command, shell=True).strip()
        if output:
            self.say(output.decode('utf-8'))
        elif self.failure_text:
            self.say(self.failure_text)


# Example: Change the volume
# ==========================
#
# This example will can change the speaker volume of the Raspberry Pi. It uses
# the shell command SET_VOLUME to change the volume, and then GET_VOLUME gets
# the new volume. The example says the new volume aloud after changing the
# volume.

class VolumeControl(object):

    """Changes the volume and says the new level."""
    
    GET_VOLUME = r'amixer get Master | grep "Front Left:" | sed "s/.*\[\([0-9]\+\)%\].*/\1/"'
    SET_VOLUME = 'amixer -q set Master %d%%'
    
    UP = 'up'
    DOWN = 'down'
    MAX = 'max'
    MUTE = 'mute'

    def __init__(self, say, keyword):
        self.say = say
        self.keyword = keyword
        self.value = None

    def run(self, voice_command):
    
        mode = voice_command.lower().replace(self.keyword, '', 1).strip()
      
        if mode == VolumeControl.UP:
            self.increment(10)
        elif mode == VolumeControl.DOWN:
            self.increment(-10)
        elif mode == VolumeControl.MAX:
            self.set(100)
        elif mode == VolumeControl.MUTE:
            self.set(0)
        elif mode:
            match = re.search(r'\d+', mode)
            if match:
                vol = int(match.group())
                self.set(vol)
            else:
                self.say('Please specify a value.')
                return
        
        self.tell()
            
    def increment(self, value):
        res = subprocess.check_output(VolumeControl.GET_VOLUME, shell=True).strip()
        vol = int(res) + value
        self.set(vol)
    
    def set(self, value):
        vol = max(0, min(100, value))
        try:
            subprocess.call(VolumeControl.SET_VOLUME % vol, shell=True)
            logging.info("volume: %s", vol)
            self.value = vol
        except (ValueError, subprocess.CalledProcessError):
            logging.exception("Error using amixer to adjust volume.")
        
    def tell(self):
        if not self.value:
            res = subprocess.check_output(VolumeControl.GET_VOLUME, shell=True).strip()
            self.value = int(res)
        self.say(_('Volume at %d %%.') % self.value)


# Example: Repeat after me
# ========================
#
# This example will repeat what the user said. It shows how you can access what
# the user said, and change what you do or how you respond.

class RepeatAfterMe(object):

    """Repeats the user's command."""

    def __init__(self, say, keyword):
        self.say = say
        self.keyword = keyword

    def run(self, voice_command):
        # The command still has the 'repeat after me' keyword, so we need to
        # remove it before saying whatever is left.
        to_repeat = voice_command.lower().replace(self.keyword, '', 1)
        self.say(to_repeat)


# Example: Change Philips Light Color
# ====================================
#
# This example will change the color of the named bulb to that of the
# HEX RGB color and respond with 'ok'
#
# actor.add_keyword(_('change to ocean blue'), \
# 		ChangeLightColor(say, "philips-hue", "Lounge Lamp", "0077be"))

class ChangeLightColor(object):

    """Change a Philips Hue bulb color."""

    def __init__(self, say, bridge_address, bulb_name, hex_color):
        self.converter = Converter()
        self.say = say
        self.hex_color = hex_color
        self.bulb_name = bulb_name
        self.bridge_address = bridge_address

    def run(self):
        bridge = self.find_bridge()
        if bridge:
            light = bridge.get_light_objects("name")[self.bulb_name]
            light.on = True
            light.xy = self.converter.hex_to_xy(self.hex_color)
            self.say(_("Ok"))

    def find_bridge(self):
        try:
            bridge = phue.Bridge(self.bridge_address)
            bridge.connect()
            return bridge
        except phue.PhueRegistrationException:
            logging.info("hue: No bridge registered, press button on bridge and try again")
            self.say(_("No bridge registered, press button on bridge and try again"))


# Power: Shutdown or reboot the pi
# ================================
# Shuts down the pi or reboots with a response
#

class PowerCommand(object):
    """Shutdown or reboot the pi"""

    SHUTDOWN = 0
    RESTART = 1
    
    def __init__(self, say, command):
        self.say = say
        self.command = command

    def run(self, voice_command):
        if self.command == self.SHUTDOWN:
            self.say("Shutting down, goodbye")
            subprocess.call("sudo shutdown now", shell=True)
        elif self.command == self.RESTART:
            self.say("Rebooting")
            subprocess.call("sudo shutdown -r now", shell=True)
        else:
            logging.error("Error identifying power command.")
            self.say("Sorry I didn't identify that command")

# =========================================
# Makers! Implement your own actions here.
# =========================================

class YouTubePlayer(object):

    """Plays song from YouTube."""
    
    def __init__(self, say, keyword):
        self.say = say
        self.keyword = keyword
        self._init_player()
        self._init_gpio(23)
        
    def run(self, voice_command):
    
        track = voice_command.lower().replace(self.keyword, '', 1).strip()
        
        if not track:
            self.say('Please specify a song')
            return
        
        ydl_opts = {
            'default_search': 'ytsearch1:',
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
        }
        
        meta = None
        try:
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                meta = ydl.extract_info(track, download=False)
        except Exception as e:
            self.say('Failed to find ' + track)
            return
        
        if not meta:
            self.say('Failed to find ' + track)
            return
            
        track_info = meta['entries'][0]
        if not track_info:
            self.say('Failed to find ' + track)
            return
   
        url = track_info['url']
        logging.debug(url)
        media = self.instance.media_new(url)
        self.player.set_media(media)
   
        # Keep only words and use negative lookahead and lookbehind to remove '_'
        pattern = r'(?!_)\w+(?<!_)'
        self.now_playing = ' '.join(re.findall(pattern, track_info['title']))
        logging.info(self.now_playing)
        self.say('Now playing ' + self.now_playing)
        
        self.player.play()

        self.done = False
        while not self.done:
            time.sleep(1)
            
    def _init_gpio(self, channel, polarity=GPIO.FALLING, pull_up_down=GPIO.PUD_UP):
        self.input_value = polarity == GPIO.RISING
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(channel, GPIO.IN, pull_up_down=pull_up_down)
        try:
            GPIO.add_event_detect(channel, polarity, callback=self._on_input_event)
        except RuntimeError:
            logging.info('Event already added')
            GPIO.add_event_callback(channel, self._on_input_event)
            
    def _init_player(self):
        self.now_playing = None
        self.done = False
        self.instance = vlc.get_default_instance()
        self.player = self.instance.media_player_new()
        events = self.player.event_manager()
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_player_event)
        events.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_player_event)
    
    def _on_input_event(self, channel):
        if GPIO.input(channel) == self.input_value:
            self.player.stop()
            self.done = True

    def _on_player_event(self, event):
        if event.type == vlc.EventType.MediaPlayerEndReached:
            self.done = True
        elif event.type == vlc.EventType.MediaPlayerEncounteredError:
            self.say("Can't play " + self.now_playing)
            self.done = True
        

class TuneInRadio(object):

    """Plays a radio stream from TuneIn radio"""
    
    BASE_URL = 'http://tunein.com/'
    FILTER_STATIONS = 'Stations'
    
    def __init__(self, say, keyword):
        self.say = say
        self.keyword = keyword
        self._init_player()
        self._init_gpio(23)
        
    def run(self, voice_command):
        
        search_str = voice_command.lower().replace(self.keyword, '', 1).strip()
     
        if not search_str:
            self.say('Please specify a station')
            return
     
        stations = self._search(search_str)
        if not stations:
            self.say("Didn't find any stations")
            return
            
        station = stations[0]
        url = self._get_stream_url(station['Id'])
        if not url:
            self.say("Didn't find any streams")
            return
        
        logging.debug(url)
        media = self.instance.media_new(url)
        self.player.set_media(media)
        
        self.now_playing = station['Title']
        logging.info(self.now_playing)
        self.say('Now playing ' + self.now_playing)
        
        self.player.play()

        self.done = False
        while not self.done:
            time.sleep(1)
            
    def _init_gpio(self, channel, polarity=GPIO.FALLING, pull_up_down=GPIO.PUD_UP):
        self.input_value = polarity == GPIO.RISING
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(channel, GPIO.IN, pull_up_down=pull_up_down)
        try:
            GPIO.add_event_detect(channel, polarity, callback=self._on_input_event)
        except RuntimeError:
            logging.info('Event already added')
            GPIO.add_event_callback(channel, self._on_input_event)
    
    def _init_player(self):
        self.now_playing = None
        self.done = False
        self.instance = vlc.get_default_instance()
        self.player = self.instance.media_player_new()
        events = self.player.event_manager()
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_player_event)
        events.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_player_event)
    
    def _on_input_event(self, channel):
        if GPIO.input(channel) == self.input_value:
            self.player.stop()
            self.done = True
            
    def _on_player_event(self, event):
        if event.type == vlc.EventType.MediaPlayerEndReached:
            self.done = True
        elif event.type == vlc.EventType.MediaPlayerEncounteredError:
            self.say("Can't play " + self.now_playing)
            self.done = True

    def _search(self, search_str, search_filter=FILTER_STATIONS):
    
        ret_results= None
        
        url = TuneInRadio.BASE_URL + 'search/?query=' + urllib.parse.quote(search_str)
        logging.debug(url)
        req = urllib.request.Request(url)
        fp = urllib.request.urlopen(req)
        xml_str = fp.read().decode('ascii', 'ignore')
        fp.close()
        
        pattern = r'TuneIn.payload = (\{.*\})'
        result = re.search(pattern, xml_str)
        
        if not result:
            return None
        
        payload = result.group(1)
        result = json.loads(payload)
        
        categories = result['ContainerGuideItems']['containers']
        for category in categories:
            if category['Title'] == search_filter:
                ret_results = category['GuideItems']
                break;
        
        return ret_results
                
    def _get_stream_url(self, station_id):
    
        url = TuneInRadio.BASE_URL + 'station/?stationId=' + str(station_id)
        logging.debug(url)
        req = urllib.request.Request(url)
        fp = urllib.request.urlopen(req)
        xml_str = fp.read().decode('ascii', 'ignore')
        fp.close()
        
        pattern = r'"StreamUrl":"(.*?)"'
        result = re.search(pattern, xml_str)
        
        if not result.group(1):
            return None
        
        json_url = 'http:' + result.group(1)
        streams = self._get_stream_list(json_url)
        
        if not streams:
            return None
            
        stream = streams[0]
        return stream['Url']
        
    def _get_stream_list(self, url):
        
        logging.debug(url)
        req = urllib.request.Request(url)
        fp = urllib.request.urlopen(req)
        json_str = fp.read().decode('ascii', 'ignore')
        fp.close()
        
        result = json.loads(json_str)
        return result['Streams']
        

def make_actor(say):
    """Create an actor to carry out the user's commands."""

    actor = actionbase.Actor()

    actor.add_keyword(
        _('ip address'), SpeakShellCommandOutput(
            say, "ip -4 route get 1 | head -1 | cut -d' ' -f8",
            _('I do not have an ip address assigned to me.')))

    actor.add_keyword(_('repeat after me'),
                      RepeatAfterMe(say, _('repeat after me')))

    # =========================================
    # Makers! Add your own voice commands here.
    # =========================================

    actor.add_keyword(_('power off'), PowerCommand(say, PowerCommand.SHUTDOWN))
    actor.add_keyword(_('turn off'), PowerCommand(say, PowerCommand.SHUTDOWN))
    
    actor.add_keyword(_('reboot'), PowerCommand(say, PowerCommand.RESTART))
    actor.add_keyword(_('restart'), PowerCommand(say, PowerCommand.RESTART))
    
    actor.add_keyword(_('volume'), VolumeControl(say, _('volume')))
    actor.add_keyword(_('play'), YouTubePlayer(say,_('play')))
    actor.add_keyword(_('radio'), TuneInRadio(say,_('radio')))

    return actor


def add_commands_just_for_cloud_speech_api(actor, say):
    """Add simple commands that are only used with the Cloud Speech API."""
    def simple_command(keyword, response):
        actor.add_keyword(keyword, SpeakAction(say, response))

    simple_command('alexa', _("We've been friends since we were both starter projects"))
    simple_command(
        'beatbox',
        'pv zk pv pv zk pv zk kz zk pv pv pv zk pv zk zk pzk pzk pvzkpkzvpvzk kkkkkk bsch')
    simple_command(_('clap'), _('clap clap'))
    simple_command('google home', _('She taught me everything I know.'))
    simple_command(_('hello'), _('hello to you too'))
    simple_command(_('tell me a joke'),
                   _('What do you call an alligator in a vest? An investigator.'))
    simple_command(_('three laws of robotics'),
                   _("""The laws of robotics are
0: A robot may not injure a human being or, through inaction, allow a human
being to come to harm.
1: A robot must obey orders given it by human beings except where such orders
would conflict with the First Law.
2: A robot must protect its own existence as long as such protection does not
conflict with the First or Second Law."""))
    simple_command(_('where are you from'), _("A galaxy far, far, just kidding. I'm from Seattle."))
    simple_command(_('your name'), _('A machine has no name'))

    actor.add_keyword(_('time'), SpeakTime(say))
