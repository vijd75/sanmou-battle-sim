% Plot current Cao Pi calibration samples and linear candidates.
clear; close all; clc;

intellect_steal = [182.39 201.77 240 295 300.23 308.2 336.03];
steal = [9.72 9.87 10.15 10.54 10.57 10.62 10.80];

intellect_reduction = [240 262 308.2 336.03];
reduction = [16.18 16.70 17.74 18.35];

font_name = 'Microsoft YaHei';
figure('Color', 'w', 'Position', [100 100 1400 620]);

subplot(1, 2, 1);
plot_linear(intellect_steal, steal, '夺取智力', '夺取智力（点）', font_name);

subplot(1, 2, 2);
plot_linear(intellect_reduction, reduction, '夺取受到伤害降低', '夺取减伤（%）', font_name);

sgtitle('权御九锡：曹丕智力与效果关系', 'FontName', font_name, 'FontSize', 18, 'FontWeight', 'bold');
exportgraphics(gcf, 'calibration_plot.png', 'Resolution', 180);

function plot_linear(x, y, title_text, y_label, font_name)
    coefficients = polyfit(x, y, 1);
    x_fit = linspace(min(x) - 5, max(x) + 5, 200);
    y_fit = polyval(coefficients, x_fit);
    predictions = polyval(coefficients, x);
    residual = y - predictions;
    rmse = sqrt(mean(residual .^ 2));

    scatter(x, y, 58, [0.05 0.35 0.75], 'filled');
    hold on;
    plot(x_fit, y_fit, 'LineWidth', 2.2, 'Color', [0.85 0.20 0.10]);
    grid on;
    box on;
    xlabel('曹丕智力', 'FontName', font_name, 'FontSize', 12);
    ylabel(y_label, 'FontName', font_name, 'FontSize', 12);
    title(title_text, 'FontName', font_name, 'FontSize', 14);
    legend('实测数据', '线性拟合', 'Location', 'best', 'FontName', font_name);
    equation = sprintf('y = %.4fx %+.4f\nRMSE = %.4f', coefficients(1), coefficients(2), rmse);
    text(0.05, 0.92, equation, 'Units', 'normalized', 'FontName', font_name, ...
        'FontSize', 11, 'BackgroundColor', [1 1 1 0.78], 'Margin', 5);
    set(gca, 'FontName', font_name, 'FontSize', 11);
end
