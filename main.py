import asyncio
import aiohttp
import aiofiles
import os
import logging
import json
import vdf

# Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Define global variables
repos = ['ManifestHub/ManifestHub', 'hansaes/ManifestAutoUpdate', 'Auiowu/ManifestAutoUpdate', 'tymolu233/ManifestAutoUpdate', 'qwq-xinkeng/awaqwqmain']  # Add multiple repositories here
games_list_file = 'steam_games.json'  # File to store game list


# Helper function to handle errors
def stack_error(e):
    return f"{type(e).__name__}: {e}"


# Fetch game list from Steam API
async def fetch_steam_game_list():
    url = 'https://api.steampowered.com/ISteamApps/GetAppList/v2/'
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            if r.status == 200:
                data = await r.json()
                game_list = data['applist']['apps']
                # Save game list to a file
                async with aiofiles.open(games_list_file, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(game_list, ensure_ascii=False, indent=4))
                log.info("✅ 游戏列表已更新")
            else:
                log.error("⚠ 获取游戏列表失败")


# Load game list from file
async def load_game_list():
    if not os.path.exists(games_list_file):
        await fetch_steam_game_list()
    async with aiofiles.open(games_list_file, 'r', encoding='utf-8') as f:
        data = await f.read()
        return json.loads(data)


# Find appid by game name using substring matching
async def find_appid_by_name(game_name):
    game_list = await load_game_list()
    game_names = {str(game['appid']): game['name'] for game in game_list}

    # Use case-insensitive substring matching
    matches = [(appid, name) for appid, name in game_names.items() if game_name.lower() in name.lower()]

    if matches:
        print("🔍 找到以下匹配的游戏:")
        for idx, (appid, name) in enumerate(matches[:10], 1):  # Limit to first 10 matches
            print(f"{idx}. {name} (AppID: {appid})")

        choice = input("请选择游戏编号：")
        if choice.isdigit() and 1 <= int(choice) <= len(matches[:10]):
            selected_appid, selected_game = matches[int(choice) - 1]
            log.info(f"✅ 选择的游戏: {selected_game} (AppID: {selected_appid})")  # Add confirmation message
            return selected_appid, selected_game
    log.error("⚠ 未找到匹配的游戏")
    return None, None

# Async function to download a file from a list of URLs
async def get(sha, path, repo):
    url_list = [
        f'https://gcore.jsdelivr.net/gh/{repo}@{sha}/{path}',
        f'https://fastly.jsdelivr.net/gh/{repo}@{sha}/{path}',
        f'https://cdn.jsdelivr.net/gh/{repo}@{sha}/{path}',
        f'https://ghproxy.org/https://raw.githubusercontent.com/{repo}/{sha}/{path}',
        f'https://raw.dgithub.xyz/{repo}/{sha}/{path}'
    ]
    retry = 3
    async with aiohttp.ClientSession() as session:
        while retry:
            for url in url_list:
                try:
                    async with session.get(url, ssl=False) as r:
                        if r.status == 200:
                            return await r.read()
                        else:
                            log.error(f'🔄 获取失败: {path} - 状态码: {r.status}')
                except aiohttp.ClientError:
                    log.error(f'🔄 获取失败: {path} - 连接错误')
            retry -= 1
            log.warning(f'🔄 重试剩余次数: {retry} - {path}')
    log.error(f'🔄 超过最大重试次数: {path}')
    return None  # Return None if download fails


# Async function to get manifest data and collect depot information
async def get_manifest(sha, path, save_dir, repo):
    collected_depots = []
    try:
        if path.endswith('.manifest'):
            save_path = os.path.join(save_dir, path)

            if os.path.exists(save_path):
                log.warning(f'👋 已存在清单: {path}')
                return collected_depots

            content = await get(sha, path, repo)
            if content:
                log.info(f'🔄 清单下载成功: {path}')
                # Save the manifest file to the directory
                async with aiofiles.open(save_path, 'wb') as f:
                    await f.write(content)

        # Attempt to download Key.vdf or config.vdf
        elif path in ['Key.vdf', 'config.vdf']:
            content = await get(sha, path, repo)
            if content:
                log.info(f'🔄 密钥下载成功: {path}')
                depots_config = vdf.loads(content.decode(encoding='utf-8'))
                for depot_id, depot_info in depots_config['depots'].items():
                    collected_depots.append((depot_id, depot_info['DecryptionKey']))
    except KeyboardInterrupt:
        raise
    except Exception as e:
        log.error(f'处理失败: {path} - {stack_error(e)}')
        raise
    return collected_depots


# Async main function to orchestrate downloading and processing
async def download_and_process(app_id, game_name):
    app_id_list = list(filter(str.isdecimal, app_id.strip().split('-')))
    app_id = app_id_list[0]

    # Create a directory for storing the manifest and Lua files
    save_dir = f'[{app_id}]{game_name}'
    os.makedirs(save_dir, exist_ok=True)

    # Iterate over each repository
    for repo in repos:
        log.info(f"🔍 Searching in repository: {repo}")

        url = f'https://api.github.com/repos/{repo}/branches/{app_id}'
        async with aiohttp.ClientSession() as session:
            async with session.get(url, ssl=False) as r:
                r_json = await r.json()
                if 'commit' in r_json:
                    sha = r_json['commit']['sha']
                    tree_url = r_json['commit']['commit']['tree']['url']
                    date = r_json['commit']['commit']['author']['date']
                    async with session.get(tree_url, ssl=False) as r2:
                        r2_json = await r2.json()
                        if 'tree' in r2_json:
                            collected_depots = []

                            # Attempt to find Key.vdf first, then config.vdf
                            vdf_paths = ['Key.vdf', 'config.vdf']
                            for vdf_path in vdf_paths:
                                vdf_result = await get_manifest(sha, vdf_path, save_dir, repo)
                                if vdf_result:
                                    collected_depots.extend(vdf_result)
                                    break  # Stop once a valid VDF is found

                            # Process each manifest in the tree
                            for item in r2_json['tree']:
                                if item['path'].endswith('.manifest'):
                                    result = await get_manifest(sha, item['path'], save_dir, repo)
                                    collected_depots.extend(result)

                            if collected_depots:
                                log.info(f'✅ 清单最后更新时间：{date}')
                                log.info(f'✅ 入库成功: {app_id} 在仓库 {repo}')
                                return collected_depots, save_dir

        log.warning(f"⚠ 游戏未在仓库 {repo} 中找到。继续搜索下一个仓库。")

    log.error(f'⚠ 清单下载失败: {app_id} 在所有仓库中')
    return [], save_dir


# Function to parse VDF files and generate Lua script
def parse_vdf_to_lua(depot_info, appid, save_dir):
    lua_lines = []

    # Add the appid to the Lua script
    lua_lines.append(f'addappid({appid})')

    for depot_id, decryption_key in depot_info:
        lua_lines.append(f'addappid({depot_id},1,"{decryption_key}")')

        # Find all manifest files for the depot
        manifest_files = [f for f in os.listdir(save_dir) if f.startswith(depot_id + "_") and f.endswith(".manifest")]
        for manifest_file in manifest_files:
            manifest_id = manifest_file[len(depot_id) + 1:-len(".manifest")]
            lua_lines.append(f'setManifestid({depot_id},"{manifest_id}",0)')

    return "\n".join(lua_lines)


# Main function to run the entire process
def main():
    user_input = input("请输入appid或游戏英文名：").strip()

    # Check if the input is numeric (appid) or string (game name)
    if user_input.isdigit():
        appid = user_input
        game_name = None
    else:
        # Use precise matching to find the appid by game name
        appid, game_name = asyncio.run(find_appid_by_name(user_input))
        if not appid:
            print("未找到匹配的游戏。请尝试其他名称。")
            return

    # If the game name is not provided directly, fetch it
    if not game_name:
        game_list = asyncio.run(load_game_list())
        game_name = next((game['name'] for game in game_list if str(game['appid']) == appid), None)

    # Start the async download and process function
    collected_depots, save_dir = asyncio.run(download_and_process(appid, game_name))

    # Proceed to generate the Lua script only if depots are collected
    if collected_depots:
        lua_script = parse_vdf_to_lua(collected_depots, appid, save_dir)

        # Write the Lua script to a file in the save directory
        lua_file_path = os.path.join(save_dir, f'{appid}.lua')
        with open(lua_file_path, 'w', encoding='utf-8') as lua_file:
            lua_file.write(lua_script)

        print(f"生成 {game_name} 解锁文件成功")
        print(f"将 {save_dir} 文件夹内所有文件拖动到 steamtools 的悬浮窗上")
        print(f"并按提示关闭 steam 后重新打开即可下载游玩 {game_name}")

if __name__ == "__main__":
    main()
    input("按任意键退出...")