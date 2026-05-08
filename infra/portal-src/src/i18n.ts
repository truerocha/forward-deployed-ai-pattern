import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

const resources = {
  'en-US': {
    translation: {
      "app": {
        "title": "Code Factory",
        "description": "Forward Deployed Software Factory",
        "region": "us-east-1 / production",
        "context": "AWS_REGION_CONTEXT"
      },
      "nav": {
        "flow": "Flow",
        "units": "Units",
        "reason": "Reason",
        "gates": "Gates",
        "health": "Health",
        "catalog": "Catalog"
      },
      "pipeline": {
        "title": "Task Pipeline",
        "subtitle": "Squad Execution Flow",
        "awaiting_signal": "Awaiting Task Signal",
        "placeholder": "Enter architectural instruction or refinement for Agents...",
        "interact": "Interact",
        "processing": "Processing",
        "nominal": "Nominal"
      },
      "metrics": {
        "dora_performance": "DORA Performance",
        "success_rate": "Success Rate",
        "failure_rate": "Change Failure Rate",
        "lead_time": "Lead Time (Avg)",
        "mttr": "MTTR"
      },
      "health": {
        "title": "Component Health",
        "subtitle": "Live Infrastructure Status",
        "resynced": "RESYNCED",
        "active": "Active",
        "degraded": "Degraded",
        "maintenance": "Maintenance"
      },
      "registries": {
        "title": "Infrastructure Registries",
        "subtitle": "Immutable Factory Parameters (Read-Only)"
      },
      "agents": {
        "title": "Squad Agents",
        "subtitle": "Active Instances: us-east-1",
        "autonomy_level": "SQUAD_MODE: DYNAMIC",
        "pipeline_mode": "ADR-019 Squad Architecture",
        "onboarding": "Initializing...",
        "analyzing": "Executing...",
        "standby": "Standby"
      },
      "terminal": {
        "title": "Chain of Thought",
        "subtitle": "Streaming Reasoning Timeline",
        "awaiting": "Awaiting activity..."
      },
      "branch_eval": {
        "title": "Branch Evaluation",
        "subtitle": "7-Dimension Quality Gate",
        "awaiting": "Awaiting evaluation signal",
        "merge_yes": "Merge Eligible",
        "merge_no": "Merge Blocked",
        "auto_merge": "Auto-Merge",
        "files": "files",
        "agent_label": "Branch Evaluation Agent (FDE)"
      }
    }
  },
  'pt-BR': {
    translation: {
      "app": {
        "title": "Fábrica de Código",
        "description": "Fábrica de Software Forward Deployed",
        "region": "us-east-1 / produção",
        "context": "CONTEXTO_REGIAO_AWS"
      },
      "nav": {
        "flow": "Fluxo",
        "units": "Unidades",
        "reason": "Razão",
        "gates": "Portas",
        "health": "Saúde",
        "catalog": "Catálogo"
      },
      "pipeline": {
        "title": "Orquestração de Workspace",
        "subtitle": "Motor de Amplificação de Engenharia",
        "awaiting_signal": "Aguardando Sinal da Pipeline",
        "placeholder": "Digite instruções arquiteturais ou refinement para Agentes...",
        "interact": "Interagir",
        "processing": "Processando",
        "nominal": "Nominal"
      },
      "metrics": {
        "dora_performance": "Performance DORA",
        "success_rate": "Taxa de Sucesso",
        "failure_rate": "Taxa de Falha de Mudança",
        "lead_time": "Tempo de Entrega (Média)",
        "mttr": "MTTR"
      },
      "health": {
        "title": "Saúde dos Componentes",
        "subtitle": "MALHA DE INTEGRIDADE CODE_FACTORY",
        "resynced": "RESSINCRONIZADO",
        "active": "Ativo",
        "degraded": "Degradado",
        "maintenance": "Manutenção"
      },
      "registries": {
        "title": "Registros de Infraestrutura",
        "subtitle": "Parâmetros Imutáveis da Fábrica (Somente Leitura)"
      },
      "agents": {
        "title": "Unidades Autônomas",
        "subtitle": "Status da Instância: us-east-1",
        "autonomy_level": "NÍVEL 5 AUTONOMIA PLENA",
        "pipeline_mode": "Modo Híbrido de Pipeline",
        "onboarding": "Integrando...",
        "analyzing": "Analisando Fluxo...",
        "standby": "Em Espera"
      },
      "terminal": {
        "title": "Cadeia de Pensamento",
        "subtitle": "Linha do Tempo de Raciocínio",
        "awaiting": "Aguardando atividade..."
      },
      "branch_eval": {
        "title": "Avaliacao de Branch",
        "subtitle": "Portao de Qualidade 7 Dimensoes",
        "awaiting": "Aguardando sinal de avaliacao",
        "merge_yes": "Merge Elegivel",
        "merge_no": "Merge Bloqueado",
        "auto_merge": "Auto-Merge",
        "files": "arquivos",
        "agent_label": "Agente de Avaliacao de Branch (FDE)"
      }
    }
  },
  'es': {
    translation: {
      "app": {
        "title": "Fábrica de Código",
        "description": "Fábrica de Software Forward Deployed",
        "region": "us-east-1 / producción",
        "context": "CONTEXTO_REGIÓN_AWS"
      },
      "nav": {
        "flow": "Flujo",
        "units": "Unidades",
        "reason": "Razón",
        "gates": "Puertas",
        "health": "Salud",
        "catalog": "Catálogo"
      },
      "pipeline": {
        "title": "Orquestración de Espacio de Trabajo",
        "subtitle": "Motor de Amplificación de Ingeniería",
        "awaiting_signal": "Esperando Señal de Tubería",
        "placeholder": "Ingrese instrucción arquitectónica o refinamiento para Agentes...",
        "interact": "Interactuar",
        "processing": "Procesando",
        "nominal": "Nominal"
      },
      "metrics": {
        "dora_performance": "Rendimiento DORA",
        "success_rate": "Tasa de Éxito",
        "failure_rate": "Tasa de Fallo de Cambio",
        "lead_time": "Plazo de Entrega (Promedio)",
        "mttr": "MTTR"
      },
      "health": {
        "title": "Salud de los Componentes",
        "subtitle": "MALLA DE INTEGRIDAD CODE_FACTORY",
        "resynced": "RESINCRO",
        "active": "Activo",
        "degraded": "Degradado",
        "maintenance": "Mantenimiento"
      },
      "registries": {
        "title": "Registros de Infraestructura",
        "subtitle": "Parámetros Inmutables de la Fábrica (Solo Lectura)"
      },
      "agents": {
        "title": "Unidades Autónomas",
        "subtitle": "Estado de la Instancia: us-east-1",
        "autonomy_level": "NIVEL 5 AUTONOMÍA TOTAL",
        "pipeline_mode": "Modo Híbrido de Tubería",
        "onboarding": "Integrando...",
        "analyzing": "Analizando Flujo de Trabajo...",
        "standby": "En Espera"
      },
      "terminal": {
        "title": "Cadena de Pensamiento",
        "subtitle": "Línea de Tiempo de Razonamiento en Streaming",
        "awaiting": "Esperando actividad..."
      },
      "branch_eval": {
        "title": "Evaluacion de Branch",
        "subtitle": "Puerta de Calidad 7 Dimensiones",
        "awaiting": "Esperando senal de evaluacion",
        "merge_yes": "Merge Elegible",
        "merge_no": "Merge Bloqueado",
        "auto_merge": "Auto-Merge",
        "files": "archivos",
        "agent_label": "Agente de Evaluacion de Branch (FDE)"
      }
    }
  }
};

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: "en-US",
    fallbackLng: "en-US",
    interpolation: {
      escapeValue: false
    }
  });

export default i18n;
