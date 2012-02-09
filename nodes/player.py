#!/usr/bin/env python


def _configure():
    from roslib import load_manifest
    load_manifest('futzy')


class Control:
    
    def __init__(self, sock, port):
        self.sock = sock
        self.port = port

    def __call__(self, data):
        # Is this okay multithreaded?
        from rospy import loginfo
        self.sock.sendto(data.data, ('127.0.0.1', self.port))


def init(sock, port, team):
    """
    Inits the connection with rcssserver. Returns a tuple of (port, side,
    player_number) on success or raises an error on failure. Given no response
    from the server, it just pauses.
    """
    # TODO Escaping or constraints on team name?
    from errno import EAGAIN
    from re import match
    from rospy import loginfo
    from socket import error
    from time import sleep
    # Turn off blocking while trying to attach. We might need to send init
    # repeatedly because the server might not be up yet.
    sock.setblocking(False)
    try:
        while True:
            try:
                sock.sendto(
                    '(init %s (version 15))' % team, ('127.0.0.1', port))
                response = sock.recvfrom(8192)
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
        sock.setblocking(True)
    # TODO Check response data, and possibly publish it.
    # Update the port from the server response.
    content = response[0]
    matched = match(r'\(init (l|r) (\d+) (\w+)\)', content)
    if not matched:
        raise RuntimeError("Failed response from rcssserver: %s" % content)
    side = 'left' if matched.group(1) == 'l' else 'right'
    player_number = int(matched.group(2))
    port = response[1][1]
    # TODO Real player number.
    return port, side, player_number


def main():
    from rospy import ROSInterruptException
    try:
        run()
    except ROSInterruptException:
        pass


def run():
    from rospy import (
        get_time, loginfo, init_node, is_shutdown, Publisher, Subscriber)
    from socket import AF_INET, SOCK_DGRAM, socket
    from std_msgs.msg import String
    sock = socket(AF_INET, SOCK_DGRAM)
    port = 6000
    try:
        # Set up.
        sock.bind(('', 0))
        # TODO Argument for team name.
        team = 'test'
        port, side, player_number = init(sock, port, team)
        # TODO Stay anonymous or use launch file to manage?
        node_name = 'player_%s_%02d' % (side, player_number)
        init_node(node_name)

        # Prepare IO.
        stream = sense(sock, port)
        raw_sensor_pub = Publisher('%s/raw_sensor' % node_name, String)
        raw_control_sub = Subscriber(
            '%s/raw_control' % node_name, String, Control(sock, port))
        try:
            while not is_shutdown():
                # There is an inherent pause.
                sensor_data = stream.next()
                raw_sensor_pub.publish(String(sensor_data))
            # In case the Ctrl+C happened not when waiting on rcss socket io.
            stream.send(True)
        except StopIteration:
            # This is expected.
            pass
        # Be polite.
        sock.sendto('(bye)', ('127.0.0.1', port))
    finally:
        sock.close()


def sense(sock, port):
    from errno import EAGAIN, EINTR
    from socket import AF_INET, error
    while True:
        try:
            data = sock.recvfrom(8192)
            done = yield data[0]
            if done:
                # Respond to Ctrl+C not on our watch.
                break
        except error as err:
            if err.errno == EINTR:
                # Presumably Ctrl+C happened while blocking on socket io.
                return
            else:
                raise


_configure()
if __name__ == '__main__':
    main()
