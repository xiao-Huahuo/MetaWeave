/** Temporary, unsaved onboarding drafts; discarded when the global entry unmounts. */
export interface ModelDraft {
  modelName: string
  baseUrl: string
  apiKey: string
}
export interface AuthDraft {
  username: string
  password: string
  confirmation: string
  libraryName: string
  knowledgeDir: string
  large: ModelDraft
  small: ModelDraft
  vision: ModelDraft
  mineruKey: string
  mineruModel: string
  vlmEnabled: boolean
  ocrEnabled: boolean
  visionEnabled: boolean
  proxyUrl: string
  webSearchEnabled: boolean
  memoryEnabled: boolean
  sensitiveWordsEnabled: boolean
  safetyEnabled: boolean
  dshEnabled: boolean
  primaryColor: string
  softColor: string
}
