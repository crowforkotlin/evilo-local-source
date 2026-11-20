# evilo-local-source

生成 N 个单插件 catalog，聚合成一个 Ed25519 签名的订阅索引，通过局域网 HTTP 服务验证 evilo 的订阅与验签流程。

## 目录结构

```text
.
├── .gitignore
├── README.md
├── gen.sh                  一条命令入口
├── generate.py             生成 catalog、确保 HTTP 服务、重建索引
├── serve.py                单独起服务或检查服务状态
├── scripts/
│   └── build_index.py      抓取 catalog、聚合、签名
└── build/                  生成产物（不提交）
```

`build/` 由 `generate.py` 创建和清理：

```text
build/
├── plugin-000/…            每个插件一个 catalog.json
├── sources.txt             catalog URL 列表
├── collection.json         索引名与 indexUrl
├── index.json              聚合结果（被签名的字节）
├── index.json.sig          Ed25519 签名
├── index.json.pub          公钥
├── repo.json               订阅入口
└── server.log              HTTP 访问日志
```

## 要求

- Python 3.8 或更高版本，仅使用标准库。
- 真机测试时手机与电脑在同一网段。

## 快速开始

```sh
bash gen.sh --COUNT 600 --ip 10.42.0.1 --port 8080
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--COUNT` | `100` | 插件数量 |
| `--ip` | `10.42.0.1` | 写进 catalog 与索引的地址 |
| `--port` | `8080` | HTTP 端口 |

等价于直接运行：

```sh
python3 generate.py 600 http://10.42.0.1:8080
```

在 evilo 里添加订阅源 `http://10.42.0.1:8080/repo.json`，勾选明文 HTTP。

## generate.py 做了什么

1. 清理 `build/` 中的 `plugin-*` 与索引产物，同时清掉旧版留在仓库根目录的同类文件。
2. 写入 `build/plugin-xxx/catalog.json`、`build/sources.txt`、`build/collection.json`。
3. 确保 `BASE` 端口有 HTTP 服务：已能访问就复用；端口被旧版服务占用时停掉并重启；否则后台启动 `http.server` 并服务 `build/`，日志写入 `build/server.log`。
4. 运行 `scripts/build_index.py`，生成 `build/index.json`、`build/index.json.sig`、`build/index.json.pub`、`build/repo.json`。

## 单独起服务

```sh
python3 serve.py 8080
```

结果分三种：

- 端口已在服务：打印 `server already serving on port 8080; nothing to do`，退出 0。
- 端口被其他进程占用：打印一行错误，退出 1。
- 端口空闲：前台监听 `0.0.0.0:8080`。

不会输出 `Address already in use` 堆栈。第二个参数可指定目录，例如 `python3 serve.py 8080 build`。

## 只重建索引

```sh
EVILO_SUBSCRIBE_KEY_HEX=9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60 \
  python3 scripts/build_index.py
```

默认读写 `build/`；设置 `EVILO_BUILD_DIR` 可改用其他目录。未提供 `EVILO_SUBSCRIBE_KEY_HEX` 时只写 `index.json`，不生成签名和公钥。

`build_index.py` 逐个抓取 `sources.txt` 中的 catalog，保留每个插件 `availableVersions` 里 `versionCode` 最大的一个，再按插件 id 排序写入索引。

## 局域网访问

- 服务监听 `0.0.0.0:<port>`；本机地址用 `ip -4 addr` 查看。
- ufw 启用时放行：`sudo ufw allow 8080/tcp`，测完用 `sudo ufw delete allow 8080/tcp` 删除。
- Android 模拟器访问宿主机用 `10.0.2.2`；真机用电脑的局域网地址。
- 地址写进 catalog 和索引，换 IP 后必须重新生成并重建索引。

## 能验证与不能验证

| 能验证 | 不能验证 |
| --- | --- |
| 索引解析、Ed25519 验签、指纹匹配、篡改拒绝 | 实际安装（需要真实签名的 manifest） |
| 列表数量与插件元数据 | 插件运行时行为 |
| 订阅只读取 `repo.json`、`index.json`、`index.json.sig`、`index.json.pub` | 下载与 Wasmline 加载 |

`manifestUrl` 与 `sourceArchiveUrl` 指向不存在的路径，所以能列出插件、能选版本，点安装会失败。

## 测试签名种子

`generate.py` 中的 `TEST_SEED` 是公开的固定测试值，用于让指纹在多次运行间保持不变。不要用它发布真实订阅源。真实订阅源见 [evilo-subscribe-template](https://github.com/crowforkotlin/evilo-subscribe-template)。
