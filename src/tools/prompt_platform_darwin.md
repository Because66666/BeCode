## Platform Notes (macOS)

- 当前运行平台为 macOS (darwin)。
- Shell 默认为 zsh，Bash 工具命令兼容 BSD 风格。
- 运行命令时，可以用`$HOME`替代`/Users/<用户名>`，尤其是当用户名包含`'`或者空格时。
- 核心规范：
1. **空格路径**：必须用双引号包裹。  
   ✅ `mkdir -p "/Users/Shared/My Project"`
2. **变量赋值**：等号两边无空格，引用用 `${VAR}`。  
   ✅ `BASE="/tmp/build_$(date)" && echo "${BASE}/bin"`
3. **链式执行**：依赖命令用 `&&` 连接。  
   ✅ `mkdir logs && echo "ok" > logs/init.log`
4. **sed 替换**：必须加 `-i ''`（空备份后缀）。  
   ✅ `sed -i '' 's/old/new/g' config.ini`
5. **find 执行**：`-exec` 末尾加 `\;`。  
   ✅ `find . -name "*.txt" -exec cat {} \; > all.txt`
6. **执行脚本**：加 `./`。  
   ✅ `./configure --prefix=/usr/local`