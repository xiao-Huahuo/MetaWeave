import { apiClient, API_ROUTES } from '@/router/api_routes';

export const getKBList = () => apiClient.get(API_ROUTES.KB_LIST);

export const createKB = (data) => apiClient.post(API_ROUTES.KB_CREATE, data);

export const updateKB = (id, data) => apiClient.put(API_ROUTES.KB_UPDATE(id), data);

export const deleteKB = (id) => apiClient.delete(API_ROUTES.KB_DELETE(id));

export const getFileList = (kb_id) => apiClient.get(API_ROUTES.FILE_LIST, { params: { kb_id } });

export const syncKBFiles = (kb_id) => apiClient.post(`/file/sync/${kb_id}`);
