<!--
  Favorite toggle button.

  Usage:
  Render next to files, library items, components, and sessions. The button emits toggle
  requests to the backend-backed favorites store and stops parent row clicks.
-->
<script setup lang="ts">
import { computed } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import type { FavoriteTargetType } from '@/api/favorites'
import { useFavoritesStore } from '@/stores/favorites'

defineOptions({ name: 'FavoriteButton' })

const props = withDefaults(defineProps<{
  targetType: FavoriteTargetType
  targetId: string
  libraryId?: string
  size?: number
  disabled?: boolean
  variant?: 'default' | 'v1'
}>(), {
  libraryId: undefined,
  size: 15,
  disabled: false,
  variant: 'default',
})

const favoritesStore = useFavoritesStore()
const active = computed(() => favoritesStore.isFavorite(props.targetType, props.targetId, props.libraryId))
const pending = computed(() => favoritesStore.isPending(props.targetType, props.targetId, props.libraryId))
const buttonStyle = computed(() => ({
  '--favorite-icon-size': `${props.size}px`,
  '--favorite-button-size': props.variant === 'v1' ? '28px' : `${Math.max(props.size + 9, 22)}px`,
}))

function toggleFavorite() {
  if (props.disabled || pending.value) return
  void favoritesStore.toggle(props.targetType, props.targetId, props.libraryId)
}
</script>

<template>
  <button
    class="favorite-button"
    :class="[{ active, pending }, props.variant === 'v1' ? 'v1-icon-button' : '']"
    type="button"
    :disabled="disabled || pending"
    :title="active ? '取消收藏' : '收藏'"
    :aria-label="active ? '取消收藏' : '收藏'"
    :aria-pressed="active"
    :style="buttonStyle"
    @click.stop.prevent="toggleFavorite"
    @dblclick.stop.prevent
    @mousedown.stop
  >
    <IcIcon name="star" class="favorite-icon" :size="size" />
  </button>
</template>

<style scoped>
.favorite-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: var(--favorite-button-size);
  height: var(--favorite-button-size);
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition:
    color var(--transition-fast),
    opacity var(--transition-fast);
}

.favorite-button:hover:not(:disabled) {
  color: #f2b705;
}

.favorite-button.active {
  color: #f2b705;
}

.favorite-icon {
  width: var(--favorite-icon-size);
  height: var(--favorite-icon-size);
  transition:
    fill 100ms ease,
    stroke-width 100ms ease,
    transform 100ms ease;
  animation: favorite-pop-out 400ms ease;
}

.favorite-button:hover:not(:disabled) .favorite-icon {
  transform: scale(1.1);
}

.favorite-button :deep(.favorite-icon *) {
  fill: none;
  stroke: currentColor;
}

.favorite-button.active .favorite-icon {
  animation: favorite-pop-in 400ms ease;
}

.favorite-button.active :deep(.favorite-icon *) {
  fill: currentColor;
  stroke-width: 0;
}

.favorite-button:disabled {
  cursor: default;
  opacity: 0.55;
}

.favorite-button.v1-icon-button .favorite-icon,
.favorite-button.v1-icon-button.active .favorite-icon {
  animation: none;
}

.favorite-button.v1-icon-button:hover:not(:disabled) .favorite-icon {
  transform: none;
}

.favorite-button.v1-icon-button.active :deep(.favorite-icon *) {
  fill: none;
  stroke-width: revert;
}

@keyframes favorite-pop-in {
  0% {
    transform: scale(0);
  }

  50% {
    transform: scale(1.2);
  }

  100% {
    transform: scale(1);
  }
}

@keyframes favorite-pop-out {
  0% {
    transform: scale(0);
  }

  50% {
    transform: scale(1.2);
  }

  100% {
    transform: scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .favorite-icon,
  .favorite-button.active .favorite-icon {
    animation: none;
  }

  .favorite-button:hover:not(:disabled) .favorite-icon {
    transform: none;
  }
}
</style>
