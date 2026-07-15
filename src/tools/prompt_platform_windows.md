## Platform Notes (Windows)

- 当前运行平台为 Windows。
- 命令在 `cmd.exe` 环境中执行，避免使用 Unix/macOS 专属命令（如 `ls -G`、`sed -i ''`、`date` BSD 选项），也不要使用 PowerShell 专属语法（如 `$env:`、`New-Item`、`-Force`、`if ($?)`）。
- 每条命令独立执行。
- 核心规范：
1. **用户名路径**：用`%USERPROFILE%`替代`C:\Users\<用户名>`，尤其是当用户名包含`'`或者空格时。
   ✅ `dir /b /a %USERPROFILE%\.nexus\projects`
2. **带空格、单引号的路径**：含空格的路径用短名，含单引号的路径不加引号裸写。`dir /x`是查短名的通用手段。
   ✅ `dir /b /ad C:\PROGRA~1`将列举`C:\Program Files`下的文件夹
   ⚠️ `dir /b /ad "C:\Program Files"`将返回错误`目录名语法不正确`，**命令中不要使用双引号!**
3. **环境变量**：用 `%VAR%` 读取。  
   ✅ `echo %USERNAME%`
5. **文件操作**：使用 cmd 原生命令（`copy`/`xcopy`/`move`/`del`），禁止使用 PowerShell Cmdlet。  
   ✅ `xcopy .\src\* .\dest\ /E /I /Y`
6. **创建目录**：`mkdir` 会自动创建父级目录。  
   ✅ `mkdir .\out\images`
7. **顺序执行**：用 `&` 串联（无视前步成败），用 `&&` 表示前步成功才执行后步，用 `||` 表示前步失败才执行后步。  
   ✅ `dotnet build .\sln.sln && echo 成功`
