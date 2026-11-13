import * as icons from '@element-plus/icons-vue'
const aliases = { 's-tools':'Tools', 's-operation':'Operation', 's-custom':'UserFilled', 's-home':'HomeFilled', 's-data':'Histogram', 's-order':'List', 's-management':'Management', 's-grid':'Grid', 's-open':'FolderOpened', 's-fold':'Fold', 's-unfold':'Expand', 's-platform':'Platform', 's-promotion':'Promotion', 's-flag':'Flag', 's-help':'HelpFilled', 's-marketing':'DataAnalysis', 's-check':'CircleCheckFilled', 's-ticket':'Ticket', 's-release':'Promotion', 's-finance':'Money', 'circle-close':'CircleClose', 'close-notification':'CloseNotification', 'more':'MoreFilled', 'picture-outline':'Picture', 'picture-outline-round':'PictureRounded', 'circle-plus-outline':'CirclePlus', 'delete-solid':'DeleteFilled', 'question':'QuestionFilled', 'warning-outline':'Warning', 'info':'InfoFilled', 'upload2':'UploadFilled', 'download':'Download', 'caret-bottom':'CaretBottom', 'caret-top':'CaretTop', 'caret-left':'CaretLeft', 'caret-right':'CaretRight' }
export function resolveIcon(value) {
  if (typeof value !== 'string') return value
  const name = value.replace(/^el-icon-/, '')
  return icons[aliases[name] || name.split('-').map(p => p.charAt(0).toUpperCase()+p.slice(1)).join('')] || icons.Menu
}
