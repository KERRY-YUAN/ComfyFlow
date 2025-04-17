Set WshShell = CreateObject("WScript.Shell")
' 获取 VBScript 所在的目录
' Get the directory where the VBScript resides
strScriptPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
' 构建 pythonw.exe 和 launcher.py 的完整路径
' Construct full paths to pythonw.exe and launcher.py
strPythonW = strScriptPath & "\venv\Scripts\pythonw.exe"
strLauncherPy = strScriptPath & "\launcher.py"
' 构建要执行的命令，确保路径用引号括起来以防空格
' Build the command to execute, ensuring paths are quoted for spaces
strCommand = """" & strPythonW & """ """ & strLauncherPy & """"
' 运行命令: 0 = 隐藏窗口, False = 不等待程序结束
' Run the command: 0 = hidden window, False = do not wait for the program to finish
WshShell.Run strCommand, 0, False
Set WshShell = Nothing