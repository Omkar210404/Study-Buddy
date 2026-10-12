# Networking Basics

## What a network is

A computer network is a group of devices that exchange data over shared links. Each device on the network is called a host. Data is not sent as one long stream. It is cut into small units called packets, and each packet carries the address of its destination.

A **protocol** is a set of rules that two devices follow so they can understand each other. Protocols are organised in layers, and each layer solves one part of the problem.

## The TCP/IP model

The TCP/IP model has four layers: link, internet, transport and application. The link layer moves frames between devices on the same local network. The internet layer moves packets between different networks using IP addresses. The transport layer delivers data to the right application on a host. The application layer is the layer that programs such as web browsers and mail clients use directly.

**Encapsulation** refers to wrapping the data from one layer inside the header of the layer below it. When a web page is requested, the HTTP message is placed inside a TCP segment, the segment inside an IP packet, and the packet inside a frame.

## Addresses

An IP address is a number that identifies a host on a network. An IPv4 address is 32 bits long and is usually written as four decimal numbers, such as 192.168.1.20. An IPv6 address is 128 bits long, which gives a far larger address space.

A MAC address is a 48-bit identifier that is assigned to a network interface. IP addresses can change when a device moves to another network, but the MAC address normally stays the same.

A **subnet mask** is a value that separates the network part of an IP address from the host part. With the mask 255.255.255.0, the first 24 bits name the network and the last 8 bits name the host.

## Devices

- **Switch**: a device that forwards frames inside one local network using MAC addresses.
- **Router**: a device that forwards packets between different networks using IP addresses.
- **Access point**: a device that lets wireless hosts join a wired network.
- **Firewall**: a device or program that allows or blocks traffic according to a set of rules.

The router that a host uses to reach other networks is called the default gateway.

## TCP and UDP

TCP stands for Transmission Control Protocol. TCP is a connection-oriented protocol: before any data is sent, the two hosts set up a connection with a three-way handshake. The handshake uses three messages, known as SYN, SYN-ACK and ACK. TCP numbers every byte it sends, so the receiver can put data back in order and ask for missing parts again.

UDP stands for User Datagram Protocol. UDP is a connectionless protocol that sends each datagram on its own, with no handshake and no retransmission. This makes UDP quick to start and light, so it suits live audio, video calls and DNS lookups, where a late packet is worse than a lost one.

## Ports

A port number is a 16-bit number that identifies one application on a host. Because it has 16 bits, the highest port number is 65,535. Web servers normally listen on port 80 for HTTP and port 443 for HTTPS. A socket refers to the combination of an IP address and a port number.

## DNS and DHCP

DNS stands for Domain Name System. DNS is the service that translates a name such as example.org into an IP address. A resolver is the server that looks up the answer for a client and stores it for a while, which is known as caching.

DHCP stands for Dynamic Host Configuration Protocol. DHCP is a protocol that gives a host its IP address, subnet mask, default gateway and DNS server automatically when it joins a network. Without DHCP, each of these values would have to be typed in by hand.

## Checking a connection

The `ping` command sends a small test message to another host and measures how long the reply takes. The time for a message to travel to a host and back is called the round-trip time. The `traceroute` command lists the routers that packets pass through on the way to a destination.

Latency refers to the delay before data arrives. Bandwidth means the amount of data a link can carry per second. A link can have high bandwidth and still feel slow if its latency is high.
