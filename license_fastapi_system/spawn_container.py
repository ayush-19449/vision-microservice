"""
CLI Tool to spawn, list, or stop Docker containers based on cam_id and use_case.
"""
import sys
import argparse
import json
from container_spawner import spawner, USE_CASE_CATALOG

def main():
    parser = argparse.ArgumentParser(
        description="Spawn Docker container based on camera ID and use case."
    )
    parser.add_argument("--cam-id", default=None, help="Camera identifier (e.g. cam-001)")
    parser.add_argument("--use-case", default=None, help=f"Vision use case: {', '.join(USE_CASE_CATALOG.keys())}")
    parser.add_argument("--license", default="camera.gry", help="Path to .gry or .lic license file")
    parser.add_argument("--list", action="store_true", help="List all spawned containers")
    parser.add_argument("--stop", action="store_true", help="Stop the container for given cam-id and use-case")
    parser.add_argument("--dry-run", action="store_true", help="Perform pre-flight verification without spawning container")
    parser.add_argument("--catalog", action="store_true", help="List available vision use cases")

    args = parser.parse_args()

    if args.catalog:
        print("\nAvailable Vision Use Cases & Container Specifications:")
        print("="*65)
        for name, info in USE_CASE_CATALOG.items():
            print(f" • {name:<20} -> Image: {info['image']}")
            print(f"   Description: {info['description']}")
            print(f"   Defaults   : {info.get('env_defaults')}\n")
        return

    if args.list:
        containers = spawner.list_containers()
        print("\nActive / Tracked Containers:")
        print("="*65)
        if not containers:
            print(" No active containers registered.")
        else:
            for c in containers:
                print(f" • Name      : {c.get('container_name')}")
                print(f"   Camera ID : {c.get('cam_id')}")
                print(f"   Use Case  : {c.get('use_case')}")
                print(f"   Status    : {c.get('status')}")
                print(f"   Mode      : {c.get('mode', 'docker')}")
                print(f"   Docker ID : {c.get('container_id')}\n")
        return

    if not args.cam_id or not args.use_case:
        parser.print_help()
        print("\n[!] Please specify both --cam-id and --use-case, or use --list / --catalog.")
        sys.exit(1)

    if args.stop:
        container_name = spawner.generate_container_name(args.cam_id, args.use_case)
        print(f"[*] Stopping container: {container_name}...")
        res = spawner.stop_container(container_name)
        print(f"[+] {res['message']}")
        return

    print("\n" + "="*60)
    print(f"[*] INITIATING CONTAINER SPAWN: {args.cam_id} | USE CASE: {args.use_case}")
    print("="*60)

    result = spawner.spawn(
        cam_id=args.cam_id,
        use_case=args.use_case,
        license_path=args.license,
        dry_run=args.dry_run
    )

    if result.get("success"):
        print("\n[+] SUCCESS: Container Ready / Spawned!")
        print(f" • Container Name : {result.get('container_name')}")
        print(f" • Camera ID      : {result.get('cam_id')}")
        print(f" • Use Case       : {result.get('use_case')}")
        print(f" • Docker Image   : {result.get('image')}")
        print(f" • Status         : {result.get('status')}")
        print(f" • Command Exec   : {result.get('docker_command')}")
        print(f" • Message        : {result.get('message')}")
    else:
        print(f"\n[-] FAILED TO SPAWN CONTAINER: {result.get('status_code')}")
        print(f" • Error Reason   : {result.get('message')}")
        sys.exit(1)

if __name__ == "__main__":
    main()
