from pathlib import Path

import json
import os
import subprocess

import sys
import zlib

UESAVE_TYPE_MAPS = [
    ".worldSaveData.CharacterSaveParameterMap.Key=Struct",
    ".worldSaveData.FoliageGridSaveDataMap.Key=Struct",
    ".worldSaveData.FoliageGridSaveDataMap.ModelMap.InstanceDataMap.Key=Struct",
    ".worldSaveData.MapObjectSpawnerInStageSaveData.Key=Struct",
    ".worldSaveData.ItemContainerSaveData.Key=Struct",
    ".worldSaveData.CharacterContainerSaveData.Key=Struct",
]


def main():
    if len(sys.argv) < 4:
        print("fix-host-save.py <uesave.exe> <save_path> <host_guid>")
        exit(1)

    # Warn the user about potential data loss.
    print(
        "WARNING: Running this script WILL change your save files and could \
potentially corrupt your data. It is HIGHLY recommended that you make a backup \
of your save folder before continuing. Press enter if you would like to continue."
    )
    input("> ")

    try:
        uesave_path = Path(sys.argv[1]).resolve(strict=True)  # strict will also check existence of the path
    except FileNotFoundError as exc:
        print(f"ERROR in uesave_path arg, path does not exist: '{exc.filename}'")
        exit(1)

    try:
        save_path = Path(sys.argv[2]).resolve(strict=True)
    except FileNotFoundError as exc:
        print(f"ERROR in save_path arg, path does not exist: '{exc.filename}'")

    host_guid = sys.argv[3]
    if len(host_guid) != 32:
        print(f"Warning: Host Guid '{host_guid}' is not of length 32!")

    # Apply expected formatting for the GUID.
    host_guid_formatted = "{}-{}-{}-{}-{}".format(
        host_guid[:8],
        host_guid[8:12],
        host_guid[12:16],
        host_guid[16:20],
        host_guid[20:],
    ).lower()

    level_sav_path = save_path / "Level.sav"
    host_sav_path = save_path / "Players/00000000000000000000000000000001.sav"
    host_new_sav_path = (save_path / "Players" / host_guid).with_suffix(".sav")
    level_json_path = level_sav_path.with_suffix(level_sav_path.suffix + ".json")
    host_json_path = host_sav_path.with_suffix(host_sav_path.suffix + ".json")

    # uesave_path must point directly to the executable, not just the path it is located in.
    # the .exists() check is extraneous as .resolve(strict) already checks if the path exists
    if not uesave_path.exists() or not uesave_path.is_file():
        print(
            'ERROR: Your given <uesave_path> of "'
            + str(uesave_path)
            + '" is invalid. It must point directly to the executable. For example: C:\\Users\\Bob\\.cargo\\bin\\uesave.exe'
        )
        exit(1)

    # save_path must exist in order to use it.
    if not save_path.exists():
        print(
            'ERROR: Your given <save_path> of "'
            + str(save_path)
            + '" does not exist. Did you enter the correct path to your save folder?'
        )
        exit(1)

    # The co-op host needs to have created a character on the dedicated server and that save is used for this script.
    if not host_new_sav_path.exists():
        print(
            'ERROR: Your co-op host\'s player save does not exist. Did you enter the correct GUID of your co-op host? It should look like "8E910AC2000000000000000000000000".\nDid your host create their character with the provided save? Once they create their character, a file called "'
            + str(host_new_sav_path)
            + '" should appear. Refer to steps 4&5 of the README.'
        )
        exit(1)

    # Convert save files to JSON so it is possible to edit them.
    sav_to_json(uesave_path, level_sav_path)
    sav_to_json(uesave_path, host_sav_path)
    print("Converted save files to JSON")

    # Parse our JSON files.
    with open(host_json_path) as f:
        host_json = json.load(f)
    with open(level_json_path) as f:
        level_json = json.load(f)
    print("JSON files have been parsed")

    # Replace two instances of the 00001 GUID with the former host's actual GUID.
    host_json["root"]["properties"]["SaveData"]["Struct"]["value"]["Struct"]["PlayerUId"]["Struct"]["value"][
        "Guid"
    ] = host_guid_formatted
    host_json["root"]["properties"]["SaveData"]["Struct"]["value"]["Struct"]["IndividualId"]["Struct"]["value"][
        "Struct"
    ]["PlayerUId"]["Struct"]["value"]["Guid"] = host_guid_formatted
    host_instance_id = host_json["root"]["properties"]["SaveData"]["Struct"]["value"]["Struct"]["IndividualId"][
        "Struct"
    ]["value"]["Struct"]["InstanceId"]["Struct"]["value"]["Guid"]

    # Search for and replace the final instance of the 00001 GUID with the InstanceId.
    instance_ids_len = len(
        level_json["root"]["properties"]["worldSaveData"]["Struct"]["value"]["Struct"]["CharacterSaveParameterMap"][
            "Map"
        ]["value"]
    )
    for i in range(instance_ids_len):
        instance_id = level_json["root"]["properties"]["worldSaveData"]["Struct"]["value"]["Struct"][
            "CharacterSaveParameterMap"
        ]["Map"]["value"][i]["key"]["Struct"]["Struct"]["InstanceId"]["Struct"]["value"]["Guid"]
        if instance_id == host_instance_id:
            level_json["root"]["properties"]["worldSaveData"]["Struct"]["value"]["Struct"]["CharacterSaveParameterMap"][
                "Map"
            ]["value"][i]["key"]["Struct"]["Struct"]["PlayerUId"]["Struct"]["value"]["Guid"] = host_guid_formatted
            break
    print("Changes have been made")

    # Dump modified data to JSON.
    with open(host_json_path, "w") as f:
        json.dump(host_json, f, indent=2)
    with open(level_json_path, "w") as f:
        json.dump(level_json, f, indent=2)
    print("JSON files have been exported")

    # Convert our JSON files to save files.
    json_to_sav(uesave_path, level_json_path)
    json_to_sav(uesave_path, host_json_path)
    print("Converted JSON files back to save files")

    # Clean up miscellaneous GVAS and JSON files which are no longer needed.
    clean_up_files(level_sav_path)
    clean_up_files(host_sav_path)
    print("Miscellaneous files removed")

    # We must rename the patched save file from the 00001 GUID to the host's actual GUID.
    if os.path.exists(host_new_sav_path):
        os.remove(host_new_sav_path)
    os.rename(host_sav_path, host_new_sav_path)
    print("Fix has been applied! Have fun!")


def sav_to_json(uesave_path: Path, file: Path):
    with open(file, "rb") as f:
        # Read the file
        data = f.read()
        uncompressed_len = int.from_bytes(data[0:4], byteorder="little")
        compressed_len = int.from_bytes(data[4:8], byteorder="little")
        magic_bytes = data[8:11]
        save_type = data[11]
        # Check for magic bytes
        if magic_bytes != b"PlZ":
            print(f"File {file} is not a save file, found {magic_bytes} instead of P1Z")
            return
        # Valid save types
        if save_type not in [0x30, 0x31, 0x32]:
            print(f"File {file} has an unknown save type: {save_type}")
            return
        # We only have 0x31 (single zlib) and 0x32 (double zlib) saves
        if save_type not in [0x31, 0x32]:
            print(f"File {file} uses an unhandled compression type: {save_type}")
            return
        if save_type == 0x31:
            # Check if the compressed length is correct
            if compressed_len != len(data) - 12:
                print(f"File {file} has an incorrect compressed length: {compressed_len}")
                return
        # Decompress file
        uncompressed_data = zlib.decompress(data[12:])
        if save_type == 0x32:
            # Check if the compressed length is correct
            if compressed_len != len(uncompressed_data):
                print(f"File {file} has an incorrect compressed length: {compressed_len}")
                return
            # Decompress file
            uncompressed_data = zlib.decompress(uncompressed_data)
        # Check if the uncompressed length is correct
        if uncompressed_len != len(uncompressed_data):
            print(f"File {file} has an incorrect uncompressed length: {uncompressed_len}")
            return
        # Save the uncompressed file
        with open(file.with_suffix(file.suffix + ".gvas"), "wb") as f:
            f.write(uncompressed_data)
        print(f"File {file} uncompressed successfully")
        # Convert to json with uesave
        # Run uesave.exe with the uncompressed file piped as stdin
        # Standard out will be the json string
        uesave_run = subprocess.run(
            uesave_to_json_params(uesave_path, file.with_suffix(file.suffix + ".json")),
            input=uncompressed_data,
            capture_output=True,
        )
        # Check if the command was successful
        if uesave_run.returncode != 0:
            print(f"uesave.exe failed to convert {file} (return {uesave_run.returncode})")
            print(uesave_run.stdout.decode("utf-8"))
            print(uesave_run.stderr.decode("utf-8"))
            return
        print(f"File {file} (type: {save_type}) converted to JSON successfully")


def json_to_sav(uesave_path, file):
    # Convert the file back to binary
    gvas_file = file.with_suffix(".sav.gvas")
    sav_file = file.replace(".sav")
    uesave_run = subprocess.run(uesave_from_json_params(uesave_path, file, gvas_file))
    if uesave_run.returncode != 0:
        print(f"uesave.exe failed to convert {file} (return {uesave_run.returncode})")
        return
    # Open the old sav file to get type
    with open(sav_file, "rb") as f:
        data = f.read()
        save_type = data[11]
    # Open the binary file
    with open(gvas_file, "rb") as f:
        # Read the file
        data = f.read()
        uncompressed_len = len(data)
        compressed_data = zlib.compress(data)
        compressed_len = len(compressed_data)
        if save_type == 0x32:
            compressed_data = zlib.compress(compressed_data)
        with open(sav_file, "wb") as f:
            f.write(uncompressed_len.to_bytes(4, byteorder="little"))
            f.write(compressed_len.to_bytes(4, byteorder="little"))
            f.write(b"PlZ")
            f.write(bytes([save_type]))
            f.write(bytes(compressed_data))
    print(f"Converted {file} to {sav_file}")


def clean_up_files(file: Path):
    os.remove(file.with_suffix(file.suffix + ".json"))
    os.remove(file.with_suffix(file.suffix + ".gvas"))


def uesave_to_json_params(uesave_path, out_path):
    args = [
        uesave_path,
        "to-json",
        "--output",
        out_path,
    ]
    for map_type in UESAVE_TYPE_MAPS:
        args.append("--type")
        args.append(f"{map_type}")
    return args


def uesave_from_json_params(uesave_path, input_file, output_file):
    args = [
        uesave_path,
        "from-json",
        "--input",
        input_file,
        "--output",
        output_file,
    ]
    return args


if __name__ == "__main__":
    main()
