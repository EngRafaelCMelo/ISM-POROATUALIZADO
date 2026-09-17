# Firmware legado

A integração que ligava o flowmeter à UART2 do ESP32 foi removida do build
de produção na versão 2.2.0. O código anterior permanece recuperável no
histórico Git anterior a esta versão e **não deve ser usado na arquitetura
atual**.

Na arquitetura definitiva, o ESP32 lê exclusivamente a pressão via ADS1115.
O flowmeter é ligado diretamente ao computador por USB–RS485.

`teste_modbus_flow_meter/` contém somente o diagnóstico histórico por
MAX3485/UART2. Seus endereços, funções e formatos não representam a
configuração validada e o sketch não deve ser gravado no equipamento de
produção.
