#!/bin/bash

# Function to check and install required dependencies
check_dependencies() {
    local dependencies=("curl" "wget" "jq" "parallel")
    local missing_deps=()

    for dep in "${dependencies[@]}"; do
        if ! command -v "$dep" >/dev/null 2>&1; then
            missing_deps+=("$dep")
        fi
    done

    if [ ${#missing_deps[@]} -ne 0 ]; then
        echo "Installing missing dependencies: ${missing_deps[*]}"
        apt-get update
        apt-get install -y "${missing_deps[@]}"
    fi
}

# Function to get system architecture
get_system_arch() {
    local arch=$(uname -m)
    if [[ "$arch" == "aarch64" ]]; then
        echo "arm64"
    else
        echo "amd64"
    fi
}

# Function to get list of Debian mirrors
get_mirrors() {
    local mirrors_url="https://www.debian.org/mirror/list"
    curl -s "$mirrors_url" | grep -o 'http[s]*://[^"]*debian/' | sort -u
}

# Function to test mirror speed
test_mirror_speed() {
    local mirror=$1
    local arch=$2
    local test_file="dists/stable/main/binary-${arch}/Packages.gz"
    local timeout=5
    local download_limit=524288  # 512KB in bytes
    local speed=0
    local base_url

    # Extract base URL
    base_url=$(echo "$mirror" | sed -E 's|(.*)/debian/.*|\1/debian|')

    # Try HTTPS first, then HTTP
    for protocol in "https" "http"; do
        local test_url="${protocol}://${base_url#*//}/${test_file}"
        local start_time=$(date +%s.%N)
        
        # Download file with size limit and timeout
        if wget -q --no-check-certificate --timeout="$timeout" -O /dev/null \
            --max-redirect=0 --tries=1 "$test_url" 2>/dev/null; then
            local end_time=$(date +%s.%N)
            local duration=$(echo "$end_time - $start_time" | bc)
            
            # Get file size
            local size=$(curl -sI "$test_url" | grep -i 'content-length' | awk '{print $2}' | tr -d '\r')
            if [ -n "$size" ]; then
                speed=$(echo "scale=2; $size / $duration / 1048576" | bc)  # Convert to MB/s
                echo "$base_url $speed"
                return 0
            fi
        fi
    done
    echo "$base_url 0"
}

export -f test_mirror_speed

# Main script
main() {
    # Check if script is run as root
    if [ "$EUID" -ne 0 ]; then 
        echo "Please run as root"
        exit 1
    fi

    # Check and install dependencies
    check_dependencies

    # Get system architecture
    ARCH=$(get_system_arch)
    echo "System architecture: $ARCH"

    # Get list of mirrors
    echo "Fetching mirror list..."
    mirrors=($(get_mirrors))
    echo "Found ${#mirrors[@]} mirrors"

    # Test mirror speeds in parallel
    echo "Testing mirror speeds..."
    results=$(printf "%s\n" "${mirrors[@]}" | \
        parallel -j 12 --progress test_mirror_speed {} "$ARCH")

    # Sort results by speed and get top 5
    echo -e "\nTop 5 mirrors by download speed:"
    echo "Mirror                                     Speed (MB/s)"
    echo "----------------------------------------------------"
    echo "$results" | sort -k2 -nr | head -n 5 | \
        while read -r mirror speed; do
            printf "%-40s %8.2f\n" "$mirror" "$speed"
        done

    # Get fastest mirror
    fastest_mirror=$(echo "$results" | sort -k2 -nr | head -n 1 | cut -d' ' -f1)
    
    if [ -n "$fastest_mirror" ]; then
        echo -e "\nSources list entries for fastest mirror:"
        echo "deb $fastest_mirror stable main contrib non-free"
        echo "deb $fastest_mirror stable-updates main contrib non-free"
    else
        echo "No working mirrors found"
    fi
}

main "$@"
