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


def sense(sock, port):
    from errno import EAGAIN, EINTR
    from socket import AF_INET, error, SOCK_DGRAM
    try:
        count = 0
        while True:
            try:
                data = sock.recvfrom(8192)
                done = yield data[0]
                if done:
                    # Respond to Ctrl+C not on our watch.
                    break
                count = 0
            except error as err:
                # EAGAIN just means data wasn't ready. With the server
                # flood as the common case, this shouldn't happen often.
                if err.errno == EAGAIN:
                    count += 1
                    continue
                elif err.errno == EINTR:
                    # Presumably Ctrl+C happened while blocking on socket io.
                    return
                else:
                    raise
    finally:
        sock.close()


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
     # TODO Stay anonymous or use launch file to manage?
    init_node('monitor', anonymous = True)
    sock = socket(AF_INET, SOCK_DGRAM)
    port = 6000
    try:
        # Set up.
        #sock.setblocking(False)
        sock.bind(('', 0))
        sock.sendto('(dispinit version 4)', ('127.0.0.1', port))
        response = sock.recvfrom(8192)
        # TODO Check response data, and possibly publish it.
        # Update the port from the server response.
        port = response[1][1]
        stream = sense(sock, port)
        raw_sensor_pub = Publisher('raw_sensor', String)
        raw_control_sub = Subscriber('raw_control', String, Control(sock, port))
        from sys import argv; loginfo("Args: %s" % argv)
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
        sock.sendto('(dispbye)', ('127.0.0.1', port))
    finally:
        sock.close()


_configure()
if __name__ == '__main__':
    main()
