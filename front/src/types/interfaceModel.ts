export type DocumentationContent = string | string[]

export type PipelineOverride = Record<string, unknown>

export type Win32MouseKeyboard =
  | "Seize"
  | "SendMessage"
  | "PostMessage"
  | "LegacyEvent"
  | "SendMessageWithCursorPos"
  | "PostMessageWithCursorPos"
  | "SendMessageWithWindowPos"
  | "PostMessageWithWindowPos"

export type Win32Screencap =
  | "GDI"
  | "FramePool"
  | "DXGI_DesktopDup"
  | "DXGI_DesktopDup_Window"
  | "PrintWindow"
  | "ScreenDC"
  | "Foreground"
  | "Background"

export type GamepadScreencap =
  | "GDI"
  | "FramePool"
  | "DXGI_DesktopDup"
  | "DXGI_DesktopDup_Window"
  | "PrintWindow"
  | "ScreenDC"

export interface Win32Controller {
  class_regex?: string
  window_regex?: string
  mouse?: Win32MouseKeyboard
  keyboard?: Win32MouseKeyboard
  screencap?: Win32Screencap
}

export type MacOSInput = "GlobalEvent" | "PostToPid"

export type MacOSScreencap = "ScreenCaptureKit"

export interface MacOSController {
  title_regex?: string
  input?: MacOSInput
  screencap?: MacOSScreencap
}

export interface PlayCoverController {
  uuid?: string
}

export interface LinuxControllerConfig {
  screencap?: "Wlr" | "PipeWire"
  input?: "Wlr" | "UInput" | "Libei"
  use_win32_vk_code?: boolean
  pipewire_source?: "Gamescope" | "Portal"
}

export type GamepadType = "Xbox360" | "DualShock4" | "DS4"

export interface GamepadController {
  class_regex?: string
  window_regex?: string
  gamepad_type?: GamepadType
  screencap?: GamepadScreencap
}

export type ControllerType = "Adb" | "Win32" | "MacOS" | "PlayCover" | "Gamepad" | "Linux"

export interface Controller {
  name: string
  label?: string
  description?: string
  icon?: string
  type: ControllerType
  adb?: Record<string, unknown>
  win32?: Win32Controller
  macos?: MacOSController
  playcover?: PlayCoverController
  gamepad?: GamepadController
  linux?: LinuxControllerConfig
  display_short_side?: number
  display_long_side?: number
  display_raw?: boolean
  permission_required?: boolean
  attach_resource_path?: string[]
  option?: string[]
}

export interface Resource {
  name: string
  label?: string
  description?: string
  icon?: string
  path: string[]
  controller?: string[]
  option?: string[]
  hash?: string
}

export interface Agent {
  child_exec: string
  child_args?: string[]
  identifier?: string
}

export interface Task {
  name: string
  label?: string
  entry: string
  default_check?: boolean
  description?: string
  doc?: DocumentationContent
  desc?: DocumentationContent
  icon?: string
  group?: string[]
  resource?: string[]
  controller?: string[]
  pipeline_override?: PipelineOverride
  option?: string[]
}

export interface Pretask {
  resource?: string[]
  controller?: string[]
  exec: string
  args?: string[]
  name?: string
  label?: string
  description?: string
  icon?: string
  option?: string[]
}

export interface Group {
  name: string
  label?: string
  description?: string
  icon?: string
  default_expand?: boolean
}

export interface SettingSection {
  name: string
  label?: string
  description?: string
  icon?: string
  option?: string[]
  default_expand?: boolean
}

export interface OptionCase {
  name: string
  label?: string
  description?: string
  icon?: string
  option?: string[]
  pipeline_override?: PipelineOverride
}

export type InputPipelineType = "string" | "int" | "bool"

export interface InputCase {
  name: string
  label?: string
  description?: string
  default?: string
  pipeline_type?: InputPipelineType
  verify?: string
  pattern_msg?: string
}

export interface HotkeyCase {
  name: string
  label?: string
  description?: string
  default?: string
}

interface OptionBase {
  label?: string
  description?: string
  icon?: string
  controller?: string[]
  resource?: string[]
  pipeline_override?: PipelineOverride
}

export interface SelectOption extends OptionBase {
  type: "select"
  cases: OptionCase[]
  default_case?: string
}

export interface InputOption extends OptionBase {
  type: "input"
  inputs: InputCase[]
}

export interface HotkeyOption extends OptionBase {
  type: "hotkey"
  hotkeys: HotkeyCase[]
}

export interface CheckboxOption extends OptionBase {
  type: "checkbox"
  cases: OptionCase[]
  default_case?: string[]
}

export interface SwitchOption extends OptionBase {
  type: "switch"
  cases: [OptionCase, OptionCase]
  default_case?: string
}

export interface ScanSelectOption extends OptionBase {
  type: "scan_select"
  scan_dir: string
  scan_filter: string
  cases: OptionCase[]
  default_case?: string
}

export type Option =
  | SelectOption
  | InputOption
  | HotkeyOption
  | CheckboxOption
  | SwitchOption
  | ScanSelectOption

export type PresetTaskOptionValue = string | string[] | Record<string, string>

export interface PresetTask {
  name: string
  enabled?: boolean
  option?: Record<string, PresetTaskOptionValue>
}

export interface Preset {
  name: string
  label?: string
  description?: string
  icon?: string
  task?: PresetTask[]
}

export interface SentryTelemetryConfig {
  dsn: string
  /** 默认 true */
  tracing?: boolean
  /** 有限数值 [0,1]，默认 1.0 */
  traces_sample_rate?: number
  /** 有限数值 [0,1]，默认 1.0 */
  failure_attachments_sample_rate?: number
  environment?: string
}

export interface TelemetryConfig {
  sentry?: SentryTelemetryConfig
}

export interface InterfaceModel {
  interface_version: 2
  languages?: Record<string, string>
  translations?: Record<string, Record<string, unknown>>
  name: string
  label?: string
  title?: string
  icon?: string
  mirrorchyan_rid?: string
  mirrorchyan_multiplatform?: boolean
  github?: string
  version?: string
  contact?: string
  license?: string
  welcome?: string
  description?: string
  controller: Controller[]
  resource: Resource[]
  group?: Group[]
  agent?: Agent | Agent[]
  task?: Task[]
  pretask?: Pretask[]
  option?: Record<string, Option>
  global_option?: string[]
  setting?: SettingSection[]
  import?: string[]
  preset?: Preset[]
  telemetry?: TelemetryConfig
}
