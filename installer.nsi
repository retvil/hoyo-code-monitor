; HoYo Code Monitor NSIS Installer Script
; Generates a Windows installer for HoYo Code Monitor

!include "MUI2.nsh"
!include "LogicLib.nsh"

; Application info
!define APP_NAME "HoYo Code Monitor"
!define APP_VERSION "1.0.0-beta.2"
!define APP_PUBLISHER "HoYo Code Monitor Contributors"
!define APP_URL "https://github.com/retvil/hoyo-code-monitor"
!define APP_EXE "hoyo-code-monitor.exe"

; Installer settings
Name "${APP_NAME} ${APP_VERSION}"
OutFile "hoyo-code-monitor-${APP_VERSION}-setup.exe"
InstallDir "$LOCALAPPDATA\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" ""
RequestExecutionLevel user

; Modern UI
!define MUI_ICON "F:\SDProject\GIPromoCode\assets\icon.ico"
!define MUI_UNICON "F:\SDProject\GIPromoCode\assets\icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "F:\SDProject\GIPromoCode\assets\installer_banner.bmp"
!define MUI_WELCOMEPAGE_TITLE "Welcome to ${APP_NAME} Setup"
!define MUI_WELCOMEPAGE_TEXT "This wizard will guide you through the installation of ${APP_NAME} ${APP_VERSION}.\n\nClick Next to continue."
!define MUI_FINISHPAGE_TITLE "Setup Complete"
!define MUI_FINISHPAGE_TEXT "Setup has finished installing ${APP_NAME} ${APP_VERSION} on your computer.\n\nClick Finish to close this wizard."
!define MUI_FINISHPAGE_RUN "Run ${APP_NAME}"
!define MUI_FINISHPAGE_RUN_FUNCTION "RunApplication"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_COMPONENTSPAGE_NODESC

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
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
Section "!Main program" SEC_MAIN
    SectionIn RO
    SetOutPath "$INSTDIR"
    
    ; Copy entire dist folder (onedir build)
    File /r "dist\hoyo-code-monitor\*.*"

    ; Ship the branded shortcut icon referenced by Start Menu/Desktop shortcuts
    SetOutPath "$INSTDIR\assets"
    File "assets\icon.ico"
    SetOutPath "$INSTDIR"
    
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
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "tray" "$INSTDIR\assets\icon.ico"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\uninstall.exe"
SectionEnd

Section "Desktop shortcut" SEC_DESKTOP
    CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "tray" "$INSTDIR\assets\icon.ico"
SectionEnd

Section /o "Autostart on Windows login" SEC_AUTOSTART
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "HoYoCodeMonitor" '"$INSTDIR\${APP_EXE}" tray'
SectionEnd

; Uninstaller section
Section "Uninstall"
    ; Remove files
    RMDir /r "$INSTDIR"
    
    ; Remove shortcuts
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
    RMDir "$SMPROGRAMS\${APP_NAME}"
    Delete "$DESKTOP\${APP_NAME}.lnk"
    
    ; Registry cleanup
    DeleteRegKey HKCU "Software\${APP_NAME}"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "HoYoCodeMonitor"
SectionEnd

; Function to run application after install
Function RunApplication
    Exec '"$INSTDIR\${APP_EXE}" tray'
FunctionEnd

; Descriptions
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MAIN} "Main program files (required)"
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} "Create a shortcut on the Desktop"
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_AUTOSTART} "Launch HoYo Code Monitor automatically when you log in to Windows"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; Language strings
LangString DESC_SecMain ${LANG_ENGLISH} "Main program files"
LangString DESC_SecMain ${LANG_RUSSIAN} "Основные файлы программы"

LangString UNINSTALL_CONFIRM ${LANG_ENGLISH} "Are you sure you want to uninstall ${APP_NAME}?"
LangString UNINSTALL_CONFIRM ${LANG_RUSSIAN} "Вы уверены, что хотите удалить ${APP_NAME}?"
