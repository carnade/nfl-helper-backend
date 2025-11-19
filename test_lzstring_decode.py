#!/usr/bin/env python3
"""
Test script to validate LZString base64 decoding order.
Tests different decoding approaches to find the correct order of operations.
"""

import base64

# The base64 string from the request
base64_data = "MYQwTgdiAmCmBcA2A7ATmQWkQZgAy4BoBWADiNw2RPwIEYAmAFmUYyMZuSMVS2RobtM2ejUTVaWfIRK1aFInkINGJXuxoAJAPIBVDNn64gA"

print("=" * 80)
print("Testing LZString Base64 Decoding")
print("=" * 80)
print(f"\nBase64 string: {base64_data}")
print(f"Base64 length: {len(base64_data)}")
print(f"Length % 4: {len(base64_data) % 4}")

# Step 1: Add padding if needed
print("\n" + "=" * 80)
print("Step 1: Add padding if needed")
print("=" * 80)
missing_padding = len(base64_data) % 4
if missing_padding:
    padded_base64 = base64_data + '=' * (4 - missing_padding)
    print(f"Added {4 - missing_padding} padding characters")
else:
    padded_base64 = base64_data
    print("No padding needed")

print(f"Padded base64: {padded_base64}")

# Step 2: Base64 decode to bytes
print("\n" + "=" * 80)
print("Step 2: Base64 decode to bytes")
print("=" * 80)
try:
    decoded_bytes = base64.b64decode(padded_base64)
    print(f"✓ Base64 decode successful")
    print(f"Decoded bytes length: {len(decoded_bytes)}")
    print(f"First 20 bytes (hex): {decoded_bytes[:20].hex()}")
    print(f"First 20 bytes (repr): {repr(decoded_bytes[:20])}")
except Exception as e:
    print(f"✗ Base64 decode failed: {e}")
    exit(1)

# Step 3: Try UTF-8 decode
print("\n" + "=" * 80)
print("Step 3: Try UTF-8 decode")
print("=" * 80)
try:
    decoded_string = decoded_bytes.decode('utf-8')
    print(f"✓ UTF-8 decode successful")
    print(f"Decoded string: {decoded_string}")
    print(f"String length: {len(decoded_string)}")
except UnicodeDecodeError as e:
    print(f"✗ UTF-8 decode failed: {e}")
    print("This is expected - the data is likely compressed")

# Step 4: Try LZString decompression
print("\n" + "=" * 80)
print("Step 4: Try LZString decompression")
print("=" * 80)

decoded_string = None

# Try lzstring package
try:
    import lzstring
    print("Trying lzstring package...")
    lzs = lzstring.LZString()
    # LZString expects the base64 string, not the decoded bytes
    decoded_string = lzs.decompressFromBase64(base64_data)
    print(f"✓ LZString decompression successful (lzstring package)")
    print(f"Decompressed string: {decoded_string}")
    print(f"String length: {len(decoded_string)}")
except ImportError:
    print("✗ lzstring package not installed")
except Exception as e:
    print(f"✗ LZString decompression failed (lzstring): {e}")

# Try alternative package name
if not decoded_string:
    try:
        from lz_string import LZString
        print("Trying lz_string package...")
        lzs = LZString()
        decoded_string = lzs.decompressFromBase64(base64_data)
        print(f"✓ LZString decompression successful (lz_string package)")
        print(f"Decompressed string: {decoded_string}")
        print(f"String length: {len(decoded_string)}")
    except ImportError:
        print("✗ lz_string package not installed")
    except Exception as e:
        print(f"✗ LZString decompression failed (lz_string): {e}")

# Step 5: Try zlib decompression as fallback
if not decoded_string:
    print("\n" + "=" * 80)
    print("Step 5: Try zlib decompression (fallback)")
    print("=" * 80)
    import zlib
    try:
        decompressed = zlib.decompress(decoded_bytes)
        decoded_string = decompressed.decode('utf-8')
        print(f"✓ zlib decompression successful")
        print(f"Decompressed string: {decoded_string}")
        print(f"String length: {len(decoded_string)}")
    except Exception as e:
        print(f"✗ zlib decompression failed: {e}")

# Step 6: Parse the result
if decoded_string:
    print("\n" + "=" * 80)
    print("Step 6: Parse player list")
    print("=" * 80)
    print(f"Full decoded string: {decoded_string}")
    
    # Check if there's a username prefix (format: "username:player_list")
    if ':' in decoded_string:
        first_colon_idx = decoded_string.index(':')
        before_colon = decoded_string[:first_colon_idx].strip()
        # If the part before the first colon is all letters (username), extract player list
        if before_colon.isalpha() and len(before_colon) > 0:
            player_list = decoded_string[first_colon_idx + 1:]  # Get everything after "username:"
            print(f"Detected username prefix: '{before_colon}'")
            print(f"Player list (after username): {player_list}")
        else:
            player_list = decoded_string
    else:
        player_list = decoded_string
    
    player_pairs = player_list.split(',')
    print(f"Found {len(player_pairs)} player entries")
    
    sleeper_ids = []
    for pair in player_pairs:
        # Handle both colon and dash delimiters
        if ':' in pair:
            sleeper_id = pair.split(':')[0].strip()
        elif '-' in pair:
            sleeper_id = pair.split('-')[0].strip()
        else:
            continue
        
        # Only add numeric sleeper IDs (skip usernames and team abbreviations like "HOU")
        if sleeper_id and sleeper_id.isdigit():
            sleeper_ids.append(sleeper_id)
            print(f"  - {sleeper_id}")
        else:
            print(f"  - {sleeper_id} (skipped - not numeric)")
    
    print(f"\n✓ Extracted {len(sleeper_ids)} sleeper IDs: {sleeper_ids}")
    
    # Check if 12547 is in the list
    if '12547' in sleeper_ids:
        print(f"\n✓ Player 12547 found in lineup - validation should work!")
    else:
        print(f"\n✗ Player 12547 NOT found in lineup")
else:
    print("\n" + "=" * 80)
    print("✗ FAILED: Could not decode the base64 string")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Install lzstring: pip install lzstring")
    print("2. Verify the base64 string is correct")
    print("3. Check if the compression format is different")

print("\n" + "=" * 80)
print("Test Complete")
print("=" * 80)

