; Genshin Code Monitor NSIS Installer Script
; Generates a Windows installer for Genshin Code Monitor

!include "MUI2.nsh"
!include "LogicLib.nsh"

; Application info
!define APP_NAME "Genshin Code Monitor"
!define APP_VERSION "0.1.0"
!define APP_PUBLISHER "Genshin Code Monitor Contributors"
!define APP_URL "https://github.com/yourusername/genshin-code-monitor"
!define APP_EXE "genshin-code-monitor.exe"

; Installer settings
Name "${APP_NAME} ${APP_VERSION}"
OutFile "genshin-code-monitor-${APP_VERSION}-setup.exe"
InstallDir "$LOCALAPPDATA\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" ""
RequestExecutionLevel user

; Modern UI
!define MUI_ICON "assets/icon.ico"
!define MUI_UNICON "assets/icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "assets/installer_banner.bmp"
!define MUI_WELCOMEPAGE_TITLE "Welcome to ${APP_NAME} Setup"
!define MUI_WELCOMEPAGE_TEXT "This wizard will guide you through the installation of ${APP_NAME} ${APP_VERSION}.\n\nClick Next to continue."
!define MUI_FINISHPAGE_TITLE "Setup Complete"
!define MUI_FINISHPAGE_TEXT "Setup has finished installing ${APP_NAME} ${APP_VERSION} on your computer.\n\nClick Finish to close this wizard."
!define MUI_FINISHPAGE_RUN "Run ${APP_NAME}"
!define MUI_FINISHPAGE_RUN_FUNCTION "RunApplication"
!define MUI_FINISHPAGE_RUN_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; Languages
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Russian"

; Sections
Section "MainSection" SEC_MAIN
    SetOutPath "$INSTDIR"
    
    ; Main executable
    File "dist\genshin-code-monitor\${APP_EXE}"
    
    ; Config file
    File "config.toml"
    
    ; Templates directory
    File /r "templates\*.html"
    
    ; Create data and logs directories
    CreateDirectory "$INSTDIR\data"
    CreateDirectory "$INSTDIR\logs"
    
    ; Create uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    ; Registry entries
    WriteRegStr HKCU "Software\${APP_NAME}" "" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME} ${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "URLInfoAbout" "${APP_URL}"
    
    ; Start menu shortcuts
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\assets\icon.ico"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\uninstall.exe"
    
    ; Desktop shortcut (optional)
    ; CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\assets\icon.ico"
SectionEnd

; Uninstaller section
Section "Uninstall"
    ; Remove files
    Delete "$INSTDIR\${APP_EXE}"
    Delete "$INSTDIR\config.toml"
    Delete "$INSTDIR\uninstall.exe"
    RMDir /r "$INSTDIR\templates"
    RMDir /r "$INSTDIR\data"
    RMDir /r "$INSTDIR\logs"
    RMDir "$INSTDIR"
    
    ; Remove shortcuts
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
    RMDir "$SMPROGRAMS\${APP_NAME}"
    
    ; Registry cleanup
    DeleteRegKey HKCU "Software\${APP_NAME}"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
SectionEnd

; Function to run application after install
Function RunApplication
    Exec '"$INSTDIR\${APP_EXE}" tray'
FunctionEnd

; Language strings
LangString DESC_SecMain ${LANG_ENGLISH} "Main program files"
LangString DESC_SecMain ${LANG_RUSSIAN} "Основные файлы программы"

LangString UNINSTALL_CONFIRM ${LANG_ENGLISH} "Are you sure you want to uninstall ${APP_NAME}?"
LangString UNINSTALL_CONFIRM ${LANG_RUSSIAN} "Вы уверены, что хотите удалить ${APP_NAME}?"