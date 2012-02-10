#!/usr/bin/env python

"""
A node to kick off rcssserver, the 2D RoboCup Soccer Server.

TODO Should the monitor be linked to this or separate. If separate, this node
TODO really does exist just to kick off (and maintain?) the server.
"""


class MonitorProxy:
    """
    TODO Unify with PlayerProxy? Rename these to just Monitor and Player?
    TODO Use a coach instead of monitor? Main difference is in sensing?
    """
    
    def __init__(self, **args):
        # TODO Better management of info?
        from Queue import Queue
        self.infos = []
        self.port = args['port']
        self.publisher = None
        # The maxsize choice here is somewhat arbitrary, but really we shouldn't
        # be falling behind at all. This just gives a bit of wiggle room without
        # letting the world fall down for cases where something crazy happens.
        # That would be a risk if we gave no size limit.
        self.responses = Queue(maxsize = 10)
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
                    # Sleep just a bit to give the server time to respond.
                    sleep(0.25)
                    response = socket.recvfrom(8192)
                    # Got a response!
                    break
                except error as err:
                    if err.errno != EAGAIN:
                        # Scary error.
                        raise
                # Try again.
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
            # TODO Parse these to store information for later retrieval.
            if message.endswith('\0'):
                message = message[:-1]
            self.infos.append(message)
            # Get the next message ready.
            response = socket.recvfrom(8192)
        # Update the port from the server response.
        self.port = response[1][1]
        self.socket = socket
        # Create a publisher for publishing. Actual publication is managed by
        # a socket select process elsewhere.
        self.publisher = Publisher('server/raw_sensor', String)

    def is_sensor_message(self, message):
        """
        Monitor sensor messages include 'show' (and 'referee' or others?).
        """
        return message.startswith('(show ')

    def send(self, request):
        """
        Send a manual request to the server, expecting a response.
        """
        self.socket.sendto(request + '\0', ('127.0.0.1', self.port))
        # TODO Might a sense response come before this request's response?
        # TODO The answer seems to be yes. Figure out what this means for
        # TODO coordinating things.
        response = self.responses.get(timeout = 1.0)
        if response.endswith('\0'):
            response = response[:-1]
        # TODO Parse for errors?
        return [response]


class PlayerProxy:

    def __init__(self, **args):
        # TODO Do nothing here, because we really want response messages out of
        # TODO the init process, and we can't really return that from __init__.
        from Queue import Queue
        # Communication info.
        self.port = args['port']
        self.responses = Queue(maxsize = 10)
        self.socket = None
        # Player info.
        self.number = None
        self.side = None
        self.team = None
        # Precompile regexps for convenience/performance (does it matter?).
        from re import compile
        self.init_response_pattern = compile(r'\(init (l|r) (\d+) (\w+)\)')
        self.sensor_message_pattern = compile(r'\((?:hear|see|sense_body) ')

    def is_sensor_message(self, message):
        """
        Monitor sensor messages include 'show' (and 'referee' or others?).
        """
        return self.sensor_message_pattern.match(message)

    def parse_init_response(self, message):
        match = self.init_response_pattern.match(message)
        if not match:
            raise RuntimeError("Bad player init response: %s" % message)
        # Pull out side and number. Ignore play mode for now.
        # Team name doesn't show up here. We need to get that elsewhere if we
        # want it.
        self.side = 'left' if match.group(1) == 'l' else 'right'
        self.number = int(match.group(2))

    def raw_control(self, request):
        self.socket.sendto(request.data + '\0', ('127.0.0.1', self.port))

    def raw_init(self, request):
        from rospy import Publisher, Subscriber
        from socket import AF_INET, SOCK_DGRAM, socket as Socket
        from std_msgs.msg import String
        # Connect and send init request.
        socket = Socket(AF_INET, SOCK_DGRAM)
        socket.bind(('', 0))
        socket.sendto(request, ('127.0.0.1', self.port))
        # TODO Check for error.
        responses = []
        while True:
            # Sample rcssclient uses a buffer size of 8192. I'm not sure what
            # guarantees exist.
            response = socket.recvfrom(8192)
            message = response[0]
            if self.is_sensor_message(message):
                # It's a sense message, not part of the original reply.
                # TODO Publish this!
                break
            if message.endswith('\0'):
                message = message[:-1]
            if message.startswith('(init '):
                self.parse_init_response(message)
            responses.append(message)
            if message.startswith('(error '):
                # For errors, that's the only message we get. Can't just spin
                # until sensor data. No player init below to worry about,
                # either.
                return responses
        # TODO Other responses perhaps.
        # TODO Register this player and kick off pub/sub on it!
        # For raw mode, don't reinterpret errors as raised exceptions.
        self.socket = socket
        self.port = response[1][1]
        # Create a publisher for publishing. Actual publication is managed by
        # a socket select process elsewhere.
        # We know that only up to 11 players are allowed per side, so hardcode
        # the digit count to 2 for convenient sorting and alignment.
        context = 'player_%s_%02d' % (self.side, self.number)
        self.publisher = Publisher('%s/raw_sensor' % context, String)
        # And subscriber, too, which automatically gets its own thread.
        self.subscriber = Subscriber(
            '%s/raw_control' % context, String, self.raw_control)
        # And provide the list of responses.
        return responses


class ServerProxy:

    def __init__(self):
        self.monitor = None
        self.params = []
        self.players = []
        self.port = 6000
        self.sockets = {}

    def find_server_exe(self, name):
        from os import listdir
        from os.path import abspath, dirname, isfile, join
        # Assume for now that the exe name and the parent dir name are the same.
        # This is good for Linux, at least.
        server_dir_name = name
        server_dir = None
        # Look for dir through parent dirs of where we start.
        # TODO Also look in parent dirs of working directory.
        # TODO Also look in system PATH.
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
            exe = join(server_dir, 'src', name)
            if not isfile(exe):
                exe = None
        else:
            exe = None
        return exe

    def parse_options(self):
        from optparse import OptionParser
        parser = OptionParser()
        parser.add_option(
            '--attach', action = 'store_true', default = False,
            help =
                "Attach to an existing rcssserver instance instead of starting "
                "a new one.")
        parser.add_option(
            '-p', '--param', action = 'append', dest = 'params',
            help =
                "Specify a rcss server parameter in the form name=value. Don't "
                "use this technique to specify parameters supported more "
                "directly. For example, use --port for port (when that's "
                "supported).")
        # Saying self.options = ... would be safer, but I want to be able to
        # override things like self.port, and this makes such things easier. It
        # just means we need to carefully name our options.
        options = parser.parse_args()[0]
        self.__dict__.update(options.__dict__)

    def run(self):
        from errno import EINTR
        from futzy.srv import Raw
        from Queue import Full
        from rospy import init_node, loginfo, Service, spin
        from select import error, select
        from std_msgs.msg import String
        from subprocess import Popen
        # Set things up.
        init_node('rcssserver')
        processes = []
        if not self.attach:
            # TODO Also support rcssmonitor display launch.
            server_exe = self.find_server_exe('rcssserver')
            # Use coach mode by default. The main use case here is for learning
            # and research, not for actual play.
            # TODO Support other parameters (like allowing offside and such)!
            # TODO Automatic rcssmonitor (display) kickoff option!
            server_args = [server_exe, 'server::coach=1']
            # Too interfering: server_args.append('server::coach_w_referee=1')
            server_args += ['server::%s' % param for param in self.params]
            print server_args
            processes.append(Popen(server_args))#, 'server::coach_w_referee=1']))
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
                    if proxy.is_sensor_message(message):
                        # Send it out on the sensor stream.
                        proxy.publisher.publish(String(message))
                    else:
                        # Queue the service response.
                        print message
                        try:
                            proxy.responses.put_nowait(message)
                        except Full:
                            # Misbehavior. Would be nice to keep the x most
                            # recent, but this will do for now.
                            # See http://stackoverflow.com/questions/6517953/clear-all-items-from-the-queue
                            with proxy.responses.queue.mutex:
                                proxy.responses.queue.clear()
            spin()
        except error as err:
            if err.args[0] != EINTR:
                # We're only okay with EINTR for now. That happens with Ctrl+C
                # when waiting on select.
                raise
        finally: 
            # TODO Manually say bye and tear down sockets?
            for process in processes:
                # Seems TERM is good enough.
                process.terminate()

    def serve_raw_init(self, request):
        player = PlayerProxy(port = self.port)
        responses = player.raw_init(request)
        if player.side is not None:
            # Must have been a good response. Finish the init process.
            self.players.append(player)
            self.sockets[player.socket] = player
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


def _configure():
    from roslib import load_manifest
    load_manifest('futzy')


def main():
    from rospy import ROSInterruptException
    try:
        server = ServerProxy()
        server.parse_options()
        server.run()
    except ROSInterruptException:
        # Official docs recommend ignoring this here.
        pass


_configure()
if __name__ == '__main__':
    main()
