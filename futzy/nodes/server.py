#!/usr/bin/env python

"""
A node to kick off rcssserver, the 2D RoboCup Soccer Server.

TODO Should the monitor be linked to this or separate. If separate, this node
TODO really does exist just to kick off (and maintain?) the server.
"""


def _configure():
    from roslib import load_manifest
    load_manifest('futzy')


def main():
    from rospy import ROSInterruptException
    try:
        server = ServerProxy()
        server.run()
    except ROSInterruptException:
        # Official docs recommend ignoring this here.
        pass


class MonitorProxy:
    """
    TODO Unify with PlayerProxy? Rename these to just Monitor and Player?
    TODO Use a coach instead of monitor? Main difference is in sensing?
    """
    
    def __init__(self, **args):
        # TODO Better management of info?
        self.infos = []
        self.port = args['port']
        self.publisher = None
        self.socket = None

    def init_pausing(self):
        """
        Initializes the monitor, pausing as needed to wait for the server to be
        up and running.
        """
        from errno import EAGAIN
        from rospy import loginfo, Publisher
        from socket import AF_INET, error, SOCK_DGRAM, socket as Socket
        from std_msgs.msg import String
        from threading import Thread
        from time import sleep
        # Turn off blocking while trying to attach. We might need to send init
        # repeatedly because the server might not be up yet.
        socket = Socket(AF_INET, SOCK_DGRAM)
        socket.setblocking(False)
        try:
            while True:
                try:
                    socket.sendto(
                        '(dispinit version 4)', ('127.0.0.1', self.port))
                    response = socket.recvfrom(8192)
                    # Got a response!
                    break
                except error as err:
                    if err.errno != EAGAIN:
                        # Scary error.
                        raise
                # Sleep and try again.
                sleep(0.25)
        finally:
            # Reset blocking state.
            socket.setblocking(True)
        # Handle the response.
        # TODO Check for error. Raise error if so, because our interface depends
        # TODO on the monitor being up.
        while True:
            message = response[0]
            if message.startswith('(show '):
                # It's a sense message, not part of the original reply.
                # TODO Publish this!
                break
            # Parse these to store information for later retrieval.
            self.infos.append(message)
            # Get the next message ready.
            response = socket.recvfrom(8192)
        # Update the port from the server response.
        self.port = response[1][1]
        self.socket = socket
        # Create a publisher for publishing. Actual publication is managed by
        # a socket select process elsewhere.
        self.publisher = Publisher('server/raw_sensor', String)

    def send(self, request):
        """
        Send a manual request to the server, expecting a response.
        TODO Might a sense response come before this request's response?
        """
        self.socket.sendto(request, ('127.0.0.1', self.port))
        response = self.socket.recv(8192)
        # TODO Parse for errors?
        return [response]


class PlayerProxy:

    def __init__(self, **args):
        # TODO Do nothing here, because we really want response messages out of
        # TODO the init process, and we can't really return that from __init__.
        self.port = args['port']
        self.socket = None
        self.thread = None

    def raw_init(self, request):
        from re import compile
        from socket import AF_INET, SOCK_DGRAM, socket as Socket
        socket = Socket(AF_INET, SOCK_DGRAM)
        socket.bind(('', 0))
        socket.sendto(request, ('127.0.0.1', self.port))
        # Sample rcssclient uses a buffer size of 8192. I'm not sure what
        # guarantees exist.
        response = socket.recvfrom(8192)
        # TODO Check for error.
        responses = [response[0]]
        sense_pattern = compile(r'\((?:hear|see|sense) ')
        while True:
            response = socket.recvfrom(8192)
            message = response[0]
            if sense_pattern.match(message):
                # It's a sense message, not part of the original reply.
                # TODO Publish this!
                break
            responses.append(message)
        # TODO Other responses perhaps.
        # TODO Register this player and kick off pub/sub on it!
        # For raw mode, don't reinterpret errors as raised exceptions.
        self.socket = socket
        self.port = response[1][1]
        return responses


class ServerProxy:
    
    def __init__(self):
        self.monitor = None
        self.players = []
        self.port = 6000
        self.sockets = {}

    def find_server_exe(self):
        from os import listdir
        from os.path import abspath, dirname, isfile, join
        # Look for rcssserver dir through parent dirs of where we start.
        # TODO Also look in parent dirs of working directory.
        # TODO Also look in system PATH.
        server_dir_name = 'rcssserver'
        server_dir = None
        current = abspath(dirname(__file__))
        while True:
            kids = listdir(current)
            if server_dir_name in kids:
                server_dir = join(current, server_dir_name)
                break
            parent = abspath(join(current, '..'))
            if parent == current:
                # Must be at root.
                break
            # Go into the parent.
            current = parent
        if server_dir:
            # Find the exe. TODO Support Windows conventions.
            # Meanwhile, on Linux, the exe matches exactly the dir name.
            exe = join(server_dir, 'src', 'rcssserver')
            if not isfile(exe):
                exe = None
        else:
            exe = None
        return exe

    def run(self):
        from errno import EINTR
        from futzy.srv import Raw
        from rospy import init_node, is_shutdown, loginfo, Service, spin
        from select import error, select
        from std_msgs.msg import String
        from subprocess import Popen
        # Set things up.
        init_node('rcssserver')
        exe = self.find_server_exe()
        # Use coach mode by default. The main use case here is for learning and
        # research, not for actual play.
        # TODO Support other parameters (like allowing offside and such)!
        # TODO Automatic rcssmonitor (display) kickoff option!
        process = Popen([exe, 'server::coach=1'])
        try:
            # Start up our monitor, waiting for the server to be ready.
            self.monitor = MonitorProxy(port = self.port)
            self.monitor.init_pausing()
            # TODO Do we need to sync on updates to sockets?
            self.sockets[self.monitor.socket] = self.monitor
            # Good to go.
            raw_service = Service('server/raw', Raw, self.serve_raw)
            # Everything is on separate threads (IO bound), so just wait here.
            loginfo("Server up and running.")
            while True:
                sockets = select(self.sockets.keys(), [], [])[0]
                for socket in sockets:
                    proxy = self.sockets[socket]
                    message = socket.recv(8192)
                    proxy.publisher.publish(String(message))
            spin()
        except error as err:
            if err.args[0] != EINTR:
                # We're only okay with EINTR for now.
                raise
        finally: 
            # TODO Also kill all threads gracefully.
            # Seems TERM is good enough.
            process.terminate()

    def serve_raw_init(self, request):
        player = PlayerProxy(port = self.port)
        responses = player.raw_init(request)
        self.players.append(player)
        return responses

    def serve_raw(self, request):
        from futzy.srv import RawResponse
        request = request.request
        if request.startswith('(init '):
            responses = self.serve_raw_init(request)
        elif request.startswith('(move '):
            # TODO Regex all the options for monitor/coach commands?
            responses = self.monitor.send(request)
        else:
            responses = ['(error unsupported_command)']
        return RawResponse(responses = responses)


_configure()
if __name__ == '__main__':
    main()
