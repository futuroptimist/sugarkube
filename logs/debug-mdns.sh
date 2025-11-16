#!/bin/bash
echo "=== System Info ==="
hostname
date -u
ip addr show eth0

echo -e "\n=== Avahi Daemon Status ==="
sudo systemctl status avahi-daemon --no-pager

echo -e "\n=== Check if mDNS port is listening ==="
sudo netstat -ulnp | grep 5353 || sudo ss -ulnp | grep 5353

echo -e "\n=== Test local mDNS resolution ==="
avahi-resolve -n sugarkube1.local
avahi-resolve -n sugarkube0.local

echo -e "\n=== Browse all mDNS services (5 second timeout) ==="
timeout 5 avahi-browse -a -t -r || echo "Browse timed out or no services found"

echo -e "\n=== Browse specific k3s service (5 second timeout) ==="
timeout 5 avahi-browse -t -r _k3s-sugar-dev._tcp || echo "Browse timed out or no k3s service found"

echo -e "\n=== Check for multicast route ==="
ip route show | grep 224.0.0.0

echo -e "\n=== Check firewall rules ==="
sudo iptables -L -n -v | grep -E "5353|mdns|multicast" || echo "No explicit firewall rules for mDNS"
sudo ufw status 2>/dev/null || echo "UFW not installed/active"

echo -e "\n=== Check if we can ping sugarkube0 ==="
ping -c 3 sugarkube0.local 2>&1 || echo "Cannot ping sugarkube0.local"

echo -e "\n=== Try to discover k3s service on sugarkube0 specifically ==="
timeout 5 avahi-browse -t -r _k3s-sugar-dev._tcp | grep sugarkube0 || echo "No sugarkube0 found"

echo -e "\n=== Check nsswitch.conf for mDNS ==="
grep mdns /etc/nsswitch.conf

echo -e "\n=== Test if we can reach sugarkube0's k3s API ==="
curl -k --connect-timeout 5 https://sugarkube0.local:6443/ping 2>&1 || echo "Cannot reach k3s API"
curl -k --connect-timeout 5 https://192.168.86.41:6443/ping 2>&1 || echo "Cannot reach k3s API via IP"

echo -e "\n=== Check for multicast group membership ==="
ip maddress show eth0

echo -e "\n=== Capture mDNS traffic (5 second sample) ==="
sudo timeout 5 tcpdump -i eth0 -n udp port 5353 2>&1 || echo "Cannot capture mDNS traffic"

echo -e "\n=== Check Avahi daemon logs (last 50 lines) ==="
sudo journalctl -u avahi-daemon -n 50 --no-pager

echo -e "\n=== DONE ==="
