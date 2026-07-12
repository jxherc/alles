export function projectFolderMessage(state) {
  if (state === 'available') return 'folder available';
  if (state === 'missing') return 'folder missing — choose its new server location';
  return 'folder required — choose a server folder to use this Project';
}
