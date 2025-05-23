:: githubvisible=true
@echo off
setlocal enabledelayedexpansion
set configFileName=environment.ini
set bitfilePath=%~dp0\BlankVI.lvbitx
set codeGenrationResultPath=%~dp0\CodeGenerationResults.lvtxt
set bitstreamPath=%cd%\SasquatchTop.bin
echo %~dp0
echo %cd%
echo %~dp0%configFileName%
echo !createBitfileExePath! %bitfilePath% %codeGenrationResultPath% %bitstreamPath%

if exist "%~dp0%configFileName%" (
  for /f "delims=" %%x in (%~dps0\%configFileName%) do (set %%x)
  "!createBitfileExePath!" "%bitfilePath%" "%codeGenrationResultPath%" "%bitstreamPath%"
  if errorlevel 1 ( 
    pushd "%~dp0.."
    echo An error occurred when converting the Vivado Design Suite bitstream to LabVIEW FPGA bitfile. Make sure the variable 'createBitfileExePath' in !cd!\%configFileName% exists and is pointing to the correct LabVIEW installation path.
    popd
  )
) else (
  pushd "%~dp0"
  echo Couldn't find !cd!\%configFileName%.
  echo Possible reason: The export is corrupted. 
  echo Solution: Try rebuilding the corresponding build specification in LabVIEW.
  popd
  exit /b 1
)