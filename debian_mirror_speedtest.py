#!/usr/bin/env python3

import requests
import concurrent.futures
import time
from urllib.parse import urljoin, urlparse
import sys
from typing import Dict, List, Tuple
import logging
from bs4 import BeautifulSoup
import urllib3
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import socket
from tqdm import tqdm
import platform

# Configure logging to only show errors
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Disable all warnings
urllib3.disable_warnings()
logging.getLogger("urllib3").setLevel(logging.ERROR)

class MirrorSpeedTester:
    def __init__(self):
        self.mirrors_url = "https://www.debian.org/mirror/list"
        self.speed_files = {
            'amd64': "dists/stable/main/binary-amd64/Packages.gz",
            'arm64': "dists/stable/main/binary-arm64/Packages.gz"
        }
        self.timeout = 1
        self.chunk_size = 65536
        self.download_limit =  512 * 1024  # 1MB limit
        self.max_connections = 12

    def get_session(self) -> requests.Session:
        """Create a session with connection settings."""
        session = requests.Session()
        retry_strategy = Retry(
            total=0,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_maxsize=self.max_connections)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def get_mirrors(self) -> List[str]:
        """Fetch list of Debian mirrors."""
        try:
            response = requests.get(self.mirrors_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            mirrors = []

            for row in soup.find_all('tr'):
                cols = row.find_all('td')
                if len(cols) >= 2:
                    link = cols[1].find('a')
                    if link and link.get('href'):
                        mirrors.append(link['href'])
            
            return list(dict.fromkeys(mirrors))

        except Exception as e:
            logger.error(f"Error fetching mirrors: {e}")
            return []

    def test_mirror_speed(self, mirror: str, test_file: str, session: requests.Session) -> Tuple[str, float]:
        """Test download speed of Packages.gz."""
        url = urljoin(mirror, test_file)
        schemes = ['https', 'http'] if mirror.startswith('http://') else ['http', 'https']
        
        for scheme in schemes:
            try:
                test_url = f"{scheme}://{urlparse(url).netloc}{urlparse(url).path}"
                start_time = time.time()
                response = session.get(
                    test_url,
                    timeout=self.timeout,
                    stream=True,
                    verify=False
                )
                response.raise_for_status()

                total_size = 0
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        total_size += len(chunk)
                        if total_size >= self.download_limit:
                            break
                        if time.time() - start_time > self.timeout:
                            break

                duration = time.time() - start_time
                if duration > 0 and total_size > 0:
                    speed = total_size / duration / 1024 / 1024  # MB/s
                    base_url = mirror[:mirror.find('/debian/')+8] if '/debian/' in mirror else mirror.rsplit('/', 4)[0]
                    return base_url, speed
            except:
                continue
        
        return None, 0

def main():
    tester = MirrorSpeedTester()
    system_arch = 'arm64' if platform.machine().startswith('aarch64') else 'amd64'
    mirrors = tester.get_mirrors()
    
    print(f"\nTesting {len(mirrors)} mirrors...")
    session = tester.get_session()
    arch_results = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=tester.max_connections) as executor:
        future_to_mirror = {
            executor.submit(tester.test_mirror_speed, mirror, tester.speed_files[system_arch], session): mirror 
            for mirror in mirrors
        }
        
        with tqdm(total=len(mirrors), desc="Testing speeds", unit="mirror") as pbar:
            for future in concurrent.futures.as_completed(future_to_mirror):
                try:
                    base_url, speed = future.result()
                    if base_url and speed > 0:
                        arch_results[base_url] = speed
                except:
                    pass
                pbar.update(1)

    # Sort and display results
    sorted_mirrors = sorted(
        arch_results.items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    if sorted_mirrors:
        print("\nTop 5 mirrors by Packages.gz download speed:")
        print("\nMirror                                     Speed (MB/s)")
        print("-" * 60)
        for mirror, speed in sorted_mirrors:
            print(f"{mirror:<40} {speed:>8.2f}")
        
        print("\nSources list entries for fastest mirror:")
        print(f"deb {sorted_mirrors[0][0]} stable main contrib non-free")
        print(f"deb {sorted_mirrors[0][0]} stable-updates main contrib non-free")
    else:
        print("\nNo working mirrors found")
    
    print(f"\nTested {len(mirrors)} mirrors, found {len(arch_results)} working")

if __name__ == "__main__":
    main()
