import json
import select
import socket
import threading
import time

import mailpile.auth
import mailpile.util
from mailpile.conn_brokers import Master as ConnBroker
from mailpile.commands import Command
from mailpile.i18n import gettext as _
from mailpile.plugins import PluginManager
from mailpile.ui import Session
from mailpile.util import *


_plugins = PluginManager(builtin=__file__)
_GUIS = {}


def UpdateGUIState():
    for gui in _GUIS.values():
        gui.change_state()


def GetUserSecret(config):
    """Return a secret that only this Unix user could know."""
    return 'FIXME12345'


class GuiOMaticConnection(threading.Thread):
    def __init__(self, config, sock, main=False):
        threading.Thread.__init__(self)
        self.daemon = True
        self.config = config
        self._am_main = True # main
        self._sock = sock
        self._state = self._state_startup
        self._lock = threading.Lock()

    def _do(self, command, **args):
        try:
            if self._sock:
                self._sock.sendall('%s %s\n' % (command, json.dumps(args)))
        except IOError:
            if self._am_main:
                from mailpile.plugins.core import Quit
                Quit(self.config.background, 'quit').run()
            self._sock = False

    def _select_sleep(self, seconds):
        r = w = x = None
        while self._sock and (seconds > 0) and not (r or w or x):
            r, w, x = select.select([self._sock], [self._sock], [self._sock],
                                    min(1, seconds))
            seconds -= 1

    def _state_startup(self, in_state):
        if in_state:
            self._do('set_status', status='startup')
            self._do('notify_user', message=_('Connected'))
            if self._am_main:
                self._do('set_item_label',
                    item='quit', label=_("Shutdown Mailpile"))
                self._do('set_item_label',
                    item='quit_button', label=_("Shutdown"))
        else:
            self._select_sleep(3)
            self._do('hide_splash_screen')
            self._do('show_main_window')
            self._do('set_item_sensitive', item='main')
            self._do('set_item_sensitive', item='browse')

    def _state_please_log_in(self, in_state):
        if in_state:
            self._do('set_status', status='attention')
            self._do('notify_user', message=_('Please log in'))

    def _state_logged_in(self, in_state):
        if in_state:
            self._do('set_status', status='normal')
            self._do('notify_user', message=_('Welcome to Mailpile!'))

    def _state_shutting_down(self, in_state):
        if in_state:
            self._do('set_status', status='shutdown')
            self._do('notify_user', message=_('Shutting down'))

    def _choose_state(self):
        if mailpile.util.QUITTING:
            return self._state_shutting_down
        elif self.config.loaded_config:
            return self._state_logged_in
        else:
            return self._state_please_log_in

    def change_state(self):
        with self._lock:
            next_state = self._choose_state()
            if next_state != self._state:
                self._state(False)
                self._state = next_state
                self._state(True)
                return True
            else:
                if self.config.index:
                    msg_count = len(self.config.index.INDEX)
                    label = _('Mailpile: %d messages') % msg_count
                elif not self.config.loaded_config:
                    label = _('Mailpile') + ': ' + _('Please log in')
                else:
                    label = _('This is Mailpile!')
                self._do('set_item_label', item="status", label=label)
                return False

    def run(self):
        tid = self.ident
        try:
            with self._lock:
                _GUIS[tid] = self
                self._state(True)
                delay = 0.5
            while self._sock:
                self._select_sleep(delay)
                if self.change_state():
                    delay = 0.5
                else:
                    delay = min(2.0, delay + 0.1)
        finally:
            del _GUIS[tid]


class ConnectToGuiOMatic(Command):
    """Connect to a waiting gui-o-matic GUI"""
    SYNOPSIS = (None, 'gui', 'gui', '[<secret>] [main|watch] <port>')
    ORDER = ('Internals', 9)
    CONFIG_REQUIRED = False
    IS_USER_ACTIVITY = False
    HTTP_CALLABLE = ('GET', 'POST')
    HTTP_AUTH_REQUIRED = False

    def command(self):
        if self.data.get('_method'):
            secret, style, port = self.args
            if secret != GetUserSecret(self.session.config):
                raise AccessError('Invalid User Secret')
        elif len(self.args) == 2:
            style, port = self.args
        elif len(self.args) == 1:
            style, port = 'main', self.args[0]

        with ConnBroker.context(need=[ConnBroker.OUTGOING_RAW]):
            guic = GuiOMaticConnection(
                self.session.config,
                socket.create_connection(('localhost', int(port))),
                main=(style == 'main'))
        guic.start()

        return self._success("OK")


_plugins.register_commands(ConnectToGuiOMatic)