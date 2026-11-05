// the link that fills Remotely Save's settings in Obsidian (the plugin's own "import settings" link).
// format from remotely-save/remotely-save src/importExport.ts (exportQrCodeUri, importQrCodeUri) and
// src/main.ts (registerObsidianProtocolHandler): obsidian://remotely-save?func=settings&version=..&vault=..&data=..
// where data is the url-encoded json of the settings to merge in. the plugin refuses the link unless
// `vault` equals the name of the vault that is open, and it replaces the whole `webdav` object,
// so every field the webdav client reads is sent. field names are WebdavConfig in src/baseTypes.ts.
export function remotelySaveLink({ address, folder = 'docs', token, vault, user = 'obsidian' }) {
  const settings = {
    serviceType: 'webdav',
    webdav: {
      address,
      username: user,
      password: token,
      authType: 'basic',
      depth: 'manual_1',
      remoteBaseDir: folder,
    },
  };
  // the handler reads only func, vault and data, so no version is sent: a shorter link is an easier code to scan
  return `obsidian://remotely-save?func=settings&vault=${encodeURIComponent(vault)}&data=${encodeURIComponent(JSON.stringify(settings))}`;
}
