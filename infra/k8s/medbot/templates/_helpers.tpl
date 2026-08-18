{{/* Naming and labels. Centralised so every object is consistently selectable. */}}

{{- define "medbot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "medbot.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "medbot.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "medbot.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "medbot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Per-component selector labels. `component` is what NetworkPolicies and Services
     match on, so it must be stable across releases. */}}
{{- define "medbot.selectorLabels" -}}
app.kubernetes.io/name: {{ include "medbot.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "medbot.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "medbot.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "medbot.secretName" -}}
{{- if .Values.secrets.existingSecret }}{{ .Values.secrets.existingSecret }}{{ else }}{{ include "medbot.fullname" . }}-secrets{{ end }}
{{- end }}

{{/* Image reference. Empty registry => bare name, which is what `kind load docker-image`
     expects; a registry is prefixed for any real cluster. */}}
{{- define "medbot.image" -}}
{{- $reg := .root.Values.image.registry -}}
{{- if $reg }}{{ printf "%s/%s:%s" $reg .name .root.Values.image.tag }}{{ else }}{{ printf "%s:%s" .name .root.Values.image.tag }}{{ end }}
{{- end }}

{{/* Environment shared by every app container.
     Split by design (D17): non-secret settings come from a ConfigMap so they are visible
     in `kubectl describe`, secrets come from a Secret so they are not. A single blob
     would put credentials into plain-text output on every debug session. */}}
{{- define "medbot.commonEnv" -}}
envFrom:
  - configMapRef:
      name: {{ include "medbot.fullname" . }}-config
  - secretRef:
      name: {{ include "medbot.secretName" . }}
{{- end }}

{{/* In-cluster dependency URLs. When deps.*.enabled is false these are absent and the
     value must come from the Secret/ConfigMap instead — that switch is the whole
     in-cluster-vs-managed portability story. */}}
{{- define "medbot.qdrantUrl" -}}
{{- if .Values.deps.qdrant.enabled }}http://{{ include "medbot.fullname" . }}-qdrant:6333{{ end }}
{{- end }}

{{- define "medbot.postgresUrl" -}}
{{- if .Values.deps.postgres.enabled -}}
postgresql+asyncpg://{{ .Values.deps.postgres.username }}:{{ .Values.deps.postgres.password }}@{{ include "medbot.fullname" . }}-postgres:5432/{{ .Values.deps.postgres.database }}
{{- end }}
{{- end }}

{{- define "medbot.redisUrl" -}}
{{- if .Values.deps.redis.enabled }}redis://{{ include "medbot.fullname" . }}-redis:6379/0{{ end }}
{{- end }}
